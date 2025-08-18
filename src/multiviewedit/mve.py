import sys
import os
import argparse
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QUrl, QObject, Signal, Slot, Property, QTimer, qVersion
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData, QVideoSink

from multiviewedit.trim import get_video_info, trim_video, trim_to_sequence
 

def handle_player_error(player_id, error, error_string):
    print(f"Player {player_id} Error: {error_string} (Code: {error})")

class VideoInfoProvider(QObject):
    frameRateChanged = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self._player = player
        self._frameRate = 0.0
        print("[VideoInfoProvider] Initialized.")
        # Connect signals
        self._player.metaDataChanged.connect(self.updateFrameRate)
        self._player.mediaStatusChanged.connect(self.handleMediaStatusChange)

    @Slot()
    def handleMediaStatusChange(self):
        status = self._player.mediaStatus()
        print(f"[VideoInfoProvider] Media status changed: {status}")
        if status == QMediaPlayer.MediaStatus.LoadedMedia or status == QMediaPlayer.MediaStatus.BufferedMedia:
            print("[VideoInfoProvider] Media loaded or buffered, attempting to update frame rate.")
            # Media is loaded or buffered, attempt to update frame rate
            self.updateFrameRate()
        elif status == QMediaPlayer.MediaStatus.NoMedia or \
             status == QMediaPlayer.MediaStatus.InvalidMedia:
            print("[VideoInfoProvider] Media is NoMedia or InvalidMedia.")
            # Media is not available or invalid, frame rate should be 0
            if self._frameRate != 0.0:
                print(f"[VideoInfoProvider] Resetting frame rate from {self._frameRate} to 0.0")
                self._frameRate = 0.0
                self.frameRateChanged.emit()
                print("[VideoInfoProvider] frameRateChanged emitted.")

    @Slot()
    def updateFrameRate(self):
        print("[VideoInfoProvider] updateFrameRate called.")
        current_status = self._player.mediaStatus()
        print(f"[VideoInfoProvider] Current media status for frame rate update: {current_status}")

        # If no valid media, ensure frame rate is 0.
        if not (current_status == QMediaPlayer.MediaStatus.LoadedMedia or \
                current_status == QMediaPlayer.MediaStatus.BufferedMedia or \
                current_status == QMediaPlayer.MediaStatus.BufferingMedia):
            print("[VideoInfoProvider] Media not in a state for valid frame rate.")
            if self._frameRate != 0.0:
                print(f"[VideoInfoProvider] Resetting frame rate from {self._frameRate} to 0.0 due to media status.")
                self._frameRate = 0.0
                self.frameRateChanged.emit()
                print("[VideoInfoProvider] frameRateChanged emitted.")
            return

        print("[VideoInfoProvider] Available metadata keys and values:")
        meta_data = self._player.metaData()

        # Build a reverse map from enum value to key name string for logging
        KEY_MAP = {}
        for key_name_str in dir(QMediaMetaData.Key):
            if not key_name_str.startswith('_'):
                try:
                    enum_val = getattr(QMediaMetaData.Key, key_name_str)
                    if isinstance(enum_val, QMediaMetaData.Key):
                        KEY_MAP[enum_val] = key_name_str
                except Exception:
                    # some attributes of the enum class might not be enum members
                    continue

        for key_enum in meta_data.keys():
            key_name = KEY_MAP.get(key_enum, "UnknownKey")
            try:
                value_str = str(meta_data.value(key_enum))
            except RuntimeError as e:
                value_str = f"<Error retrieving value: {e}>"
            print(f"  - {key_name} (Enum val: {key_enum}): {value_str}")

        # Correctly access the frame rate using the key
        new_rate_value = meta_data.value(QMediaMetaData.Key.VideoFrameRate)
        # The value can be None if not found, or 0.0, or the actual rate.
        # Ensure it's a float, default to 0.0 if not available or not a number.
        try:
            new_rate = float(new_rate_value) if new_rate_value is not None else 0.0
        except (ValueError, TypeError):
            new_rate = 0.0
            
        print(f"[VideoInfoProvider] Queried videoFrameRate (from metaData.value(QMediaMetaData.Key.VideoFrameRate)): {new_rate}")
        if self._frameRate != new_rate:
            print(f"[VideoInfoProvider] Frame rate changing from {self._frameRate} to {new_rate}")
            self._frameRate = new_rate
            self.frameRateChanged.emit()
            print("[VideoInfoProvider] frameRateChanged emitted.")
        else:
            print(f"[VideoInfoProvider] Frame rate unchanged: {self._frameRate}")

    @Property(float, notify=frameRateChanged)
    def frameRate(self):
        return self._frameRate

class FrameExporter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(list, list, int, list)
    def exportAllCurrentFrames(self, players, video_paths, reference_frame, frame_offsets):
        print(f"Exporting snapshots for reference frame: {reference_frame}")
        output_filename = f"{reference_frame:06d}.jpg"

        for i, player in enumerate(players):
            if i >= len(video_paths):
                print(f"FrameExporter Warning: more players than video paths. Skipping extra player {i}.")
                continue

            video_path = video_paths[i]
            
            p = Path(video_path)
            output_dir = p.parent / p.stem
            os.makedirs(output_dir, exist_ok=True)
            
            output_file_path = output_dir / output_filename
            
            video_sink = player.videoSink()
            if not video_sink:
                print(f"FrameExporter Error: Video sink not available for player {i+1} ({p.name}).")
                continue

            video_frame = video_sink.videoFrame()
            if not video_frame.isValid():
                print(f"FrameExporter Info: Current video frame is invalid for player {i+1} ({p.name}), likely out of bounds. Skipping.")
                continue

            image = video_frame.toImage()
            if image.isNull():
                print(f"FrameExporter Error: Failed to convert video frame to image for player {i+1} ({p.name}).")
                continue

            # Save with high quality (100)
            if image.save(str(output_file_path), "JPG", 100):
                print(f"FrameExporter: Saved snapshot for player {i+1} as {output_file_path}")
            else:
                print(f"FrameExporter Error: Failed to save snapshot for player {i+1} as {output_file_path}")

    @Slot(QMediaPlayer, str)
    def exportCurrentFrame(self, player, video_file_path):
        if not player:
            print("FrameExporter Error: Player object is invalid.")
            return

        video_sink = player.videoSink()
        if not video_sink:
            print(f"FrameExporter Error: Video sink not available for player processing {video_file_path}.")
            return

        video_frame = video_sink.videoFrame()
        if not video_frame.isValid():
            print(f"FrameExporter Error: Current video frame is invalid for {video_file_path}.")
            return

        image = video_frame.toImage()
        if image.isNull():
            print(f"FrameExporter Error: Failed to convert video frame to image for {video_file_path}.")
            return

        # Get frame rate from player's metadata
        frame_rate_value = player.metaData().value(QMediaMetaData.Key.VideoFrameRate)
        frame_rate = 0.0
        try:
            frame_rate = float(frame_rate_value) if frame_rate_value is not None else 0.0
        except (ValueError, TypeError):
            frame_rate = 0.0 # Default if conversion fails

        base_name = os.path.splitext(os.path.basename(video_file_path))[0]
        filename = ""

        if frame_rate > 0:
            current_frame_num = int((player.position() / 1000.0) * frame_rate)
            filename = f"{base_name}-frame{current_frame_num}.png"
        else:
            current_pos_ms = player.position()
            filename = f"{base_name}-pos{current_pos_ms}.png"
            print(f"FrameExporter Warning: Could not determine valid frame rate for {video_file_path}. Saving with position instead.")

        if image.save(filename):
            print(f"FrameExporter: Saved frame as {filename}")
        else:
            print(f"FrameExporter Error: Failed to save frame as {filename}")


class PlaybackManager(QObject):
    isPlayingChanged = Signal()
    currentFrameChanged = Signal()
    totalFramesChanged = Signal()

    def __init__(self, players, video_info_provider, parent=None):
        super().__init__(parent)
        self._players = players
        self._video_info_provider = video_info_provider
        self._frame_offsets = [0] * len(players)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advanceFrame)

        self._is_playing = False
        self._current_frame = 0
        self._total_frames = 0

        if self._video_info_provider:
            self._video_info_provider.frameRateChanged.connect(self._update_playback_parameters)
        if self._players:
            # Connect to duration changed of the master player
            self._players[0].durationChanged.connect(self._update_playback_parameters)

    @Slot()
    def _update_playback_parameters(self):
        rate = self._video_info_provider.frameRate
        duration = self._players[0].duration()

        if rate > 0 and duration > 0:
            new_total_frames = int((duration / 1000.0) * rate)
            if self._total_frames != new_total_frames:
                self._total_frames = new_total_frames
                self.totalFramesChanged.emit()
                self.updateAllPlayerPositions() # Update positions when parameters are ready

            self._timer.setInterval(int(1000 / rate))
        else:
            if self._total_frames != 0:
                self._total_frames = 0
                self.totalFramesChanged.emit()

    @Property(bool, notify=isPlayingChanged)
    def isPlaying(self):
        return self._is_playing

    @Property(int, notify=currentFrameChanged)
    def currentFrame(self):
        return self._current_frame

    @Property(int, notify=totalFramesChanged)
    def totalFrames(self):
        return self._total_frames

    @Slot()
    def play(self):
        if not self._is_playing and self._video_info_provider.frameRate > 0 and self._total_frames > 0:
            if self._current_frame >= self.totalFrames:
                self.seek(0)

            self._is_playing = True
            self._timer.start()
            self.isPlayingChanged.emit()

    @Slot()
    def pause(self):
        if self._is_playing:
            self._is_playing = False
            self._timer.stop()
            self.isPlayingChanged.emit()

    @Slot()
    def togglePlayPause(self):
        if self.isPlaying:
            self.pause()
        else:
            self.play()

    @Slot()
    def advanceFrame(self):
        if self._current_frame < self.totalFrames:
            self._current_frame += 1
            self.currentFrameChanged.emit()
            self.updateAllPlayerPositions()
        else:
            self.pause()

    @Slot(int)
    def seek(self, frame):
        if 0 <= frame <= self.totalFrames:
            self._current_frame = frame
            self.currentFrameChanged.emit()
            self.updateAllPlayerPositions()

    @Slot(list)
    def updateFrameOffsets(self, offsets):
        if len(offsets) == len(self._players):
            self._frame_offsets = offsets
            if not self.isPlaying:
                self.updateAllPlayerPositions()

    def updateAllPlayerPositions(self):
        rate = self._video_info_provider.frameRate
        if rate <= 0:
            return

        for i, player in enumerate(self._players):
            target_frame = self._current_frame + self._frame_offsets[i]
            position_ms = (target_frame / rate) * 1000.0
            player.setPosition(int(position_ms))


class VideoProcessor(QObject):
    exportStarted = Signal()
    exportFinished = Signal(str)

    @Slot(list, list, float, int, int)
    def exportSyncedVideos(self, video_paths, frame_offsets, frame_rate, trim_start_frame, trim_end_frame):
        if not video_paths:
            self.exportFinished.emit("No videos to export.")
            return
        if frame_rate <= 0:
            self.exportFinished.emit(f"Cannot export: Invalid frame rate ({frame_rate}).")
            return

        self.exportStarted.emit()
        thread = Thread(target=self._run_export, args=(video_paths, frame_offsets, frame_rate, 'video', trim_start_frame, trim_end_frame), daemon=True)
        thread.start()

    @Slot(list, list, float, int, int)
    def exportSyncedImageSequence(self, video_paths, frame_offsets, frame_rate, trim_start_frame, trim_end_frame):
        if not video_paths:
            self.exportFinished.emit("No videos to export.")
            return
        if frame_rate <= 0:
            self.exportFinished.emit(f"Cannot export: Invalid frame rate ({frame_rate}).")
            return

        self.exportStarted.emit()
        thread = Thread(target=self._run_export, args=(video_paths, frame_offsets, frame_rate, 'sequence', trim_start_frame, trim_end_frame), daemon=True)
        thread.start()

    def _run_export(self, video_paths, frame_offsets, frame_rate, export_type, trim_start_frame, trim_end_frame):
        #try:
        #    from trim import get_video_info, trim_video, trim_to_sequence
        #except ImportError:
        #    self.exportFinished.emit("Error: Could not import trim module. Make sure trim.py is in the same directory.")
        #    return

        try:
            # 1. Get video info (especially total frames) for all videos.
            video_infos = [get_video_info(p) for p in video_paths]
            total_frames_per_video = [info['nb_frames'] for info in video_infos]

            # 2. Determine the common, overlapping frame range on the master timeline.
            # The master video is the first one, with a timeline from 0 to its total frames.
            start_timeline_frame = 0
            end_timeline_frame = total_frames_per_video[0] - 1

            for i, offset in enumerate(frame_offsets[1:], 1):
                total_frames_i = total_frames_per_video[i]
                start_timeline_frame = max(start_timeline_frame, -offset)
                end_timeline_frame = min(end_timeline_frame, total_frames_i - 1 - offset)

            # Apply the user-defined trim range from the UI
            start_timeline_frame = max(start_timeline_frame, trim_start_frame)
            end_timeline_frame = min(end_timeline_frame, trim_end_frame)

            if start_timeline_frame >= end_timeline_frame:
                self.exportFinished.emit("No overlapping frames to export. Check video offsets and trim range.")
                return

            # 3. For each video, calculate its specific trim range and call the trim function.
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


def mve():
    print(f"Using Qt version: {qVersion()}")
    # We need to parse our arguments before creating the QGuiApplication to handle
    # the --enable-hw-decoding flag, and to separate them from Qt's arguments.
    parser = argparse.ArgumentParser(description="Play videos side-by-side.")
    parser.add_argument("video_paths", nargs='+', help="Paths to video files")
    parser.add_argument(
        "--enable-hw-decoding",
        action="store_true",
        help="Enable hardware video decoding (default: disabled, may be unstable).",
    )
    args, remaining_argv = parser.parse_known_args()

    # By default, disable hardware video decoding to work around driver/configuration issues.
    # The user can override this based on the parsed argument.
    if not args.enable_hw_decoding:
        os.environ["QT_MEDIA_DISABLE_HARDWARE_DECODING"] = "1"

    # Pass the program name and any unparsed args (like -style) to QGuiApplication.
    app = QGuiApplication([sys.argv[0]] + remaining_argv)

    engine = QQmlApplicationEngine()

    players = []
    # Keep audio_outputs and video_sinks in scope so they are not garbage collected
    audio_outputs = []
    video_sinks = []

    def on_media_status_changed_first_frame(status, player):
        # This function is intended to run only once when media is first loaded
        # to ensure the first frame is displayed. We add a flag to prevent it
        # from running multiple times due to status changes during playback/seeking.
        if not hasattr(player, '_first_frame_loaded') and status == QMediaPlayer.MediaStatus.LoadedMedia:
            player._first_frame_loaded = True
            player.play()
            player.pause()

    for i, video_path in enumerate(args.video_paths):
        player = QMediaPlayer()
        audio_output = QAudioOutput()
        if i > 0:
            audio_output.setMuted(True)
        player.setAudioOutput(audio_output)
        video_sink = QVideoSink()
        player.setVideoSink(video_sink)

        player.errorOccurred.connect(
            lambda err, err_str, player_id=i + 1: handle_player_error(str(player_id), err, err_str)
        )

        # Connect with a lambda to capture the current player instance
        player.mediaStatusChanged.connect(lambda s, p=player: on_media_status_changed_first_frame(s, p))

        players.append(player)
        audio_outputs.append(audio_output)
        video_sinks.append(video_sink)

    engine.rootContext().setContextProperty("players", players)

    if players:
        # Create and expose VideoInfoProvider for the first player
        video_info_provider = VideoInfoProvider(players[0], app)
        engine.rootContext().setContextProperty("videoInfoProvider", video_info_provider)

        playback_manager = PlaybackManager(players, video_info_provider, app)
        engine.rootContext().setContextProperty("playbackManager", playback_manager)

    # Create and expose FrameExporter
    frame_exporter = FrameExporter(app)
    engine.rootContext().setContextProperty("frameExporter", frame_exporter)

    # Create and expose VideoProcessor
    video_processor = VideoProcessor(app)
    engine.rootContext().setContextProperty("videoProcessor", video_processor)

    # Expose video paths to QML
    engine.rootContext().setContextProperty("videoPaths", args.video_paths)

    # Set video sources from command line arguments
    for i, video_path in enumerate(args.video_paths):
        video_url = QUrl.fromLocalFile(os.path.abspath(video_path))
        players[i].setSource(video_url)

    qml_file = Path(__file__).parent / "mve.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())

if __name__ == "__main__":
    mve()
