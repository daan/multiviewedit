import av
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from multiviewedit.trim import get_video_info


class VideoSource(QObject):
    """Processes a single video file in a separate thread."""
    frameReady = Signal(int, QImage)
    videoInfoReady = Signal(int, dict)

    def __init__(self, video_path, video_index, parent=None):
        super().__init__(parent)
        self._video_path = video_path
        self._video_index = video_index
        self._container = None
        self._stream = None
        self._info = None

    @Slot()
    def open(self):
        """Opens the video file and gets stream information."""
        try:
            self._info = get_video_info(self._video_path)
            self._container = av.open(self._video_path)
            self._stream = self._container.streams.video[0]
            self._stream.thread_type = "AUTO"
            self.videoInfoReady.emit(self._video_index, self._info)
        except (av.AVError, ValueError, IndexError) as e:
            print(f"Error opening video {self._video_path}: {e}")
            self.videoInfoReady.emit(self._video_index, {}) # Signal failure

    @Slot(int)
    def seek(self, frame_num):
        """Seeks to a specific frame and emits the resulting image."""
        if not self._container or not self._info or not (0 <= frame_num < self._info['nb_frames']):
            self.frameReady.emit(self._video_index, QImage())
            return

        try:
            target_pts = int(frame_num / self._info['frame_rate'] / self._stream.time_base)
            self._container.seek(target_pts, backward=True, any_frame=False, stream=self._stream)
            
            for frame in self._container.decode(self._stream):
                current_frame_num = int(frame.pts * self._stream.time_base * self._info['frame_rate'])
                if current_frame_num >= frame_num:
                    frame_rgba = frame.to_ndarray(format='rgba')
                    h, w, _ = frame_rgba.shape
                    q_image = QImage(frame_rgba.tobytes(), w, h, QImage.Format_RGBA8888)
                    self.frameReady.emit(self._video_index, q_image)
                    return
            
            self.frameReady.emit(self._video_index, QImage()) # If no frame found
        except Exception as e:
            print(f"Error seeking/decoding frame {frame_num} for video {self._video_index}: {e}")
            self.frameReady.emit(self._video_index, QImage())

    @Slot()
    def close(self):
        """Closes the video container."""
        if self._container:
            self._container.close()
