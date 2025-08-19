import sys
import argparse
import os
from pathlib import Path
from threading import Thread

from PySide6.QtCore import (
    QObject,
    QThread,
    QMetaObject,
    Q_ARG,
    Qt,
    QTimer,
    Signal,
    Property,
    QUrl,
    QDir,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine

from multiviewedit.video_source import VideoSource
from multiviewedit.image_provider import ImageProvider
from multiviewedit.trim import get_video_info, trim_video, trim_to_sequence


class VideoProcessor(QObject):
    exportStarted = Signal()
    exportFinished = Signal(str)

    @Slot(list, list, int, int)
    def exportSyncedVideos(self, video_paths, frame_offsets, trim_start_frame, trim_end_frame):
        if not video_paths:
            self.exportFinished.emit("No videos to export.")
            return

        self.exportStarted.emit()
        thread = Thread(target=self._run_export, args=(video_paths, frame_offsets, 'video', trim_start_frame, trim_end_frame), daemon=True)
        thread.start()

    @Slot(list, list, int, int)
    def exportSyncedImageSequence(self, video_paths, frame_offsets, trim_start_frame, trim_end_frame):
        if not video_paths:
            self.exportFinished.emit("No videos to export.")
            return

        self.exportStarted.emit()
        thread = Thread(target=self._run_export, args=(video_paths, frame_offsets, 'sequence', trim_start_frame, trim_end_frame), daemon=True)
        thread.start()

    def _run_export(self, video_paths, frame_offsets, export_type, trim_start_frame, trim_end_frame):
        try:
            video_infos = [get_video_info(p) for p in video_paths]
            total_frames_per_video = [info['nb_frames'] for info in video_infos]

            start_timeline_frame = 0
            end_timeline_frame = total_frames_per_video[0] - 1

            for i, offset in enumerate(frame_offsets[1:], 1):
                total_frames_i = total_frames_per_video[i]
                start_timeline_frame = max(start_timeline_frame, -offset)
                end_timeline_frame = min(end_timeline_frame, total_frames_i - 1 - offset)

            start_timeline_frame = max(start_timeline_frame, trim_start_frame)
            end_timeline_frame = min(end_timeline_frame, trim_end_frame)

            if start_timeline_frame >= end_timeline_frame:
                self.exportFinished.emit("No overlapping frames to export. Check video offsets and trim range.")
                return

            for i, path in enumerate(video_paths):
                trim_start = start_timeline_frame + frame_offsets[i]
                trim_end = end_timeline_frame + frame_offsets[i]
                p = Path(path)

                if export_type == 'video':
                    output_dir = p.parent / "synced"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / p.name
                    print(f"Trimming {path} from frame {trim_start} to {trim_end} -> {output_path}")
                    trim_video(path, output_path, trim_start, trim_end)
                    print(f"Successfully exported {output_path}")
                elif export_type == 'sequence':
                    output_dir = p.parent / p.stem
                    os.makedirs(output_dir, exist_ok=True)
                    print(f"Exporting sequence for {path} from frame {trim_start} to {trim_end} -> {output_dir}")
                    trim_to_sequence(path, output_dir, trim_start, trim_end, start_timeline_frame)
                    print(f"Successfully exported sequence for {path}")


            self.exportFinished.emit("Export complete!")

        except Exception as e:
            error_message = f"An error occurred during export: {e}"
            print(error_message)
            self.exportFinished.emit(error_message)


class VideoController(QObject):
    totalFramesChanged = Signal()
    currentFrameChanged = Signal()
    isPlayingChanged = Signal()
    frameOffsetsChanged = Signal()
    videosLoadedChanged = Signal()
    initialSizeReady = Signal(int, int)

    def __init__(self, video_paths, parent=None):
        super().__init__(parent)
        self._video_paths = video_paths
        self._video_infos = [None] * len(video_paths)
        self._workers = []
        self._threads = []
        self._loaded_videos_count = 0
        self._videos_loaded = False

        self._is_seeking = False
        self._next_seek_frame = -1
        self._pending_frames_count = 0

        self._is_playing = False
        self._current_frame = 0
        self._total_frames = 0
        self._frame_rate = 0.0
        self._frame_offsets = [0] * len(video_paths)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advance_frame)

        self.image_provider = ImageProvider()

    def setup_workers(self):
        for i, path in enumerate(self._video_paths):
            thread = QThread()
            worker = VideoSource(path, i)
            worker.moveToThread(thread)
            thread.started.connect(worker.open)
            worker.videoInfoReady.connect(self._on_video_info_ready)
            worker.frameReady.connect(self.image_provider.updateImage)
            worker.frameReady.connect(self._on_frame_ready)
            thread.finished.connect(worker.deleteLater)
            self._threads.append(thread)
            self._workers.append(worker)
            thread.start()

    def cleanup(self):
        for worker in self._workers:
            QMetaObject.invokeMethod(worker, "close", Qt.ConnectionType.QueuedConnection)
        for thread in self._threads:
            thread.quit()
            thread.wait()

    @Slot(int, dict)
    def _on_video_info_ready(self, video_index, info):
        if not info:
            print(f"Failed to load video {video_index + 1}")
            return

        self._video_infos[video_index] = info
        self._loaded_videos_count += 1
        
        if self._loaded_videos_count == len(self._video_paths):
            print("All videos loaded.")

            total_width = 0
            max_height = 0
            if self._video_infos:
                for video_info in self._video_infos:
                    if video_info:
                        total_width += video_info.get('width', 0)
                        max_height = max(max_height, video_info.get('height', 0))
                
                if total_width > 0 and max_height > 0:
                    self.initialSizeReady.emit(min(total_width, 1920), max_height)

            if self._video_infos and self._video_infos[0]:
                self._frame_rate = self._video_infos[0]['frame_rate']
                self.setTotalFrames(self._video_infos[0]['nb_frames'])
            
            if self._frame_rate > 0:
                self._timer.setInterval(int(1000 / self._frame_rate))
            
            self._videos_loaded = True
            self.videosLoadedChanged.emit()
            self.seek(0)

    @Slot(int, QImage)
    def _on_frame_ready(self, video_index, q_image):
        if self._is_seeking:
            self._pending_frames_count -= 1
            if self._pending_frames_count <= 0:
                self._is_seeking = False
                if self._next_seek_frame != -1:
                    next_frame = self._next_seek_frame
                    self._next_seek_frame = -1
                    self.seek(next_frame)

    @Property(int, notify=totalFramesChanged)
    def totalFrames(self):
        return self._total_frames
    
    def setTotalFrames(self, frames):
        if self._total_frames != frames:
            self._total_frames = frames
            self.totalFramesChanged.emit()

    @Property(int, notify=currentFrameChanged)
    def currentFrame(self):
        return self._current_frame

    @currentFrame.setter
    def currentFrame(self, frame):
        if self._current_frame != frame:
            self.seek(frame)

    @Property(bool, notify=isPlayingChanged)
    def isPlaying(self):
        return self._is_playing

    @Property(int, constant=True)
    def videoCount(self):
        return len(self._video_paths)

    @Property(list, notify=frameOffsetsChanged)
    def frameOffsets(self):
        return self._frame_offsets

    @Property(bool, notify=videosLoadedChanged)
    def videosLoaded(self):
        return self._videos_loaded

    @Slot(int, int)
    def setFrameOffset(self, index, offset):
        if 0 <= index < len(self._frame_offsets) and self._frame_offsets[index] != offset:
            self._frame_offsets[index] = offset
            self.frameOffsetsChanged.emit()
            if not self._is_playing:
                self.seek(self._current_frame)
    
    @Slot()
    def togglePlayPause(self):
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self._is_playing and self._frame_rate > 0:
            if self._current_frame >= self._total_frames -1:
                self.seek(0)
            self._is_playing = True
            self._timer.start()
            self.isPlayingChanged.emit()

    def pause(self):
        if self._is_playing:
            self._is_playing = False
            self._timer.stop()
            self.isPlayingChanged.emit()

    @Slot()
    def advance_frame(self):
        if self._current_frame < self._total_frames - 1:
            self.seek(self._current_frame + 1)
        else:
            self.pause()

    def seek(self, frame):
        if self._is_seeking:
            self._next_seek_frame = frame
            return

        self._is_seeking = True
        self._pending_frames_count = len(self._workers)

        if self._current_frame != frame:
            self._current_frame = frame
            self.currentFrameChanged.emit()

        for i, worker in enumerate(self._workers):
            target_frame = self._current_frame + self._frame_offsets[i]
            QMetaObject.invokeMethod(worker, "seek", Qt.ConnectionType.QueuedConnection, Q_ARG(int, target_frame))

def mve():
    parser = argparse.ArgumentParser(description="Sync video sources with QML.")
    parser.add_argument("video_paths", nargs='+', help="Paths to video files")
    args = parser.parse_args()

    app = QGuiApplication(sys.argv)

    controller = VideoController(args.video_paths)
    processor = VideoProcessor()

    engine = QQmlApplicationEngine()
    
    engine.addImageProvider("videosource", controller.image_provider)
    engine.rootContext().setContextProperty("controller", controller)
    engine.rootContext().setContextProperty("imageProvider", controller.image_provider)
    engine.rootContext().setContextProperty("videoProcessor", processor)
    engine.rootContext().setContextProperty("videoPaths", args.video_paths)

    dir_path = os.path.dirname(os.path.realpath(__file__))
    qml_path = QDir(dir_path).absoluteFilePath("mve.qml")
    engine.load(QUrl.fromLocalFile(qml_path))

    if not engine.rootObjects():
        sys.exit(-1)

    @Slot(int, int)
    def resize_window(width, height):
        if engine.rootObjects():
            window = engine.rootObjects()[0]
            window.setWidth(width)
            window.setHeight(height)

    controller.initialSizeReady.connect(resize_window)

    controller.setup_workers()
    
    app.aboutToQuit.connect(controller.cleanup)

    sys.exit(app.exec())

if __name__ == "__main__":
    mve()
