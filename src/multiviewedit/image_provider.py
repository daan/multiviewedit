from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class ImageProvider(QQuickImageProvider):
    imageUpdated = Signal(int)

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.images = []
        self._placeholder = QImage(1, 1, QImage.Format.Format_RGB888)
        self._placeholder.fill(0)

    def requestImage(self, id, size, requestedSize):
        try:
            image_id = id.split('?')[0]
            index = int(image_id)
            if 0 <= index < len(self.images):
                img = self.images[index]
                if not img.isNull():
                    return img
        except (ValueError, IndexError):
            pass
        return self._placeholder

    @Slot(int, QImage)
    def updateImage(self, index, image):
        if index >= len(self.images):
            self.images.extend([QImage()] * (index - len(self.images) + 1))
        self.images[index] = image
        self.imageUpdated.emit(index)
