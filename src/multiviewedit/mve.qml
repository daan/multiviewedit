import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: window
    visible: true
    width: 1280
    height: 720
    title: "QML Video Sync"

    property bool isExporting: false
    property string exportStatus: ""

    Popup {
        id: exportPopup
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        width: 400
        height: 150
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: Rectangle {
            color: "#333"
            border.color: "white"
            Text {
                padding: 10
                anchors.fill: parent
                color: "white"
                text: exportStatus
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 5

        focus: true
        Keys.onPressed: (event) => {
            if (event.key === Qt.Key_Escape) {
                Qt.quit()
            } else if (event.key === Qt.Key_Space) {
                controller.togglePlayPause()
            }
        }

        RowLayout {
            id: videoRow
            Layout.fillWidth: true
            Layout.fillHeight: true

            Repeater {
                id: videoRepeater
                model: controller.videoCount

                delegate: ColumnLayout {
                    property int imageId: 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Image {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        source: "image://videosource/" + index + "?" + parent.imageId
                        fillMode: Image.PreserveAspectFit
                    }

                    Label {
                        text: "Offset: " + (controller.frameOffsets.length > index ? controller.frameOffsets[index] : 0) + " frames"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Slider {
                        Layout.fillWidth: true
                        from: -60
                        to: 60
                        value: (controller.frameOffsets.length > index ? controller.frameOffsets[index] : 0)
                        enabled: index > 0 && controller.videosLoaded
                        onMoved: controller.setFrameOffset(index, value)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 5
            Layout.rightMargin: 5

            Slider {
                id: timelineSlider
                Layout.fillWidth: true
                from: 0
                to: controller.totalFrames > 0 ? controller.totalFrames - 1 : 0
                value: controller.currentFrame
                enabled: controller.videosLoaded

                onMoved: {
                    controller.currentFrame = value
                }
                onValueChanged: {
                    if (!pressed) {
                        controller.currentFrame = value
                    }
                }
            }

        }
        
        RangeSlider {
            id: trimSlider
            Layout.fillWidth: true
            Layout.leftMargin: 5
            Layout.rightMargin: 5
            enabled: controller.videosLoaded

            from: 0
            to: controller.totalFrames > 0 ? controller.totalFrames - 1 : 0
            first.value: 0
            second.value: to

            onToChanged: {
                if (enabled) {
                    first.value = 0;
                    second.value = to;
                }
            }
        }
        
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 10

            Button {
                text: controller.isPlaying ? "Pause" : "Play"
                enabled: controller.videosLoaded && !isExporting
                onClicked: controller.togglePlayPause()
            }
            
            Button {
                text: "Save Synced"
                enabled: controller.videosLoaded && !isExporting
                onClicked: {
                    videoProcessor.exportSyncedVideos(videoPaths, controller.frameOffsets, trimSlider.first.value, trimSlider.second.value)
                }
            }
            
            Button {
                text: "Save Synced Sequence"
                enabled: controller.videosLoaded && !isExporting
                onClicked: {
                    videoProcessor.exportSyncedImageSequence(videoPaths, controller.frameOffsets, trimSlider.first.value, trimSlider.second.value)
                }
            }
        }
    }

    Connections {
        target: imageProvider
        function onImageUpdated(index) {
            if (videoRepeater.count > index) {
                var item = videoRepeater.itemAt(index)
                if (item) {
                    item.imageId = Date.now()
                }
            }
        }
    }

    Connections {
        target: videoProcessor
        function onExportStarted() {
            isExporting = true
            exportStatus = "Exporting videos, please wait..."
            exportPopup.open()
        }
        function onExportFinished(message) {
            isExporting = false
            exportStatus = message
            // Popup remains open to show the final status
        }
    }
}
