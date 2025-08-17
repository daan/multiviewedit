import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtMultimedia

ApplicationWindow {
    id: root
    width: 1280 // Increased width for two videos
    height: 640 // Adjusted height for video, controls, and offset sliders
    visible: true
    title: qsTr("Multi-Video Player")

    property int maxFrameOffset: 60
    property var frameOffsets: []
    property bool isExporting: false
    property string exportStatus: ""

    Component.onCompleted: {
        var newOffsets = [];
        for (var i = 0; i < players.length; i++) {
            newOffsets.push(0);
        }
        frameOffsets = newOffsets;

        if (typeof playbackManager !== 'undefined') {
            playbackManager.updateFrameOffsets(frameOffsets);
        }
    }

    background: Rectangle {
        color: "black"
    }

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

    Shortcut {
        sequence: StandardKey.Cancel // StandardKey.Cancel is typically Escape
        onActivated: Qt.quit()
    }

    Shortcut {
        sequence: "Space"
        onActivated: frameExporter.exportAllCurrentFrames(players, videoPaths, playbackManager.currentFrame, frameOffsets)
    }

    Connections {
        target: videoProcessor
        function onExportStarted() {
            isExporting = true;
            exportStatus = "Exporting videos, please wait...";
            exportPopup.open();
        }
        function onExportFinished(message) {
            isExporting = false;
            exportStatus = message;
            // Popup remains open to show the final status
        }
    }


    Row {
        id: videoRow
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: controlsRect.top // Anchor to the top of the controls area
        spacing: 0 // No space between videos

        Repeater {
            model: players.length
            delegate: Column {
                width: videoRow.width / players.length
                height: videoRow.height
                spacing: 5

                property int totalFrames: videoInfoProvider.frameRate > 0 ? Math.round((players[index].duration / 1000.0) * videoInfoProvider.frameRate) : 0
                property int currentFrame: playbackManager.currentFrame + frameOffsets[index]
                property bool isOutOfBounds: index > 0 && (currentFrame < 0 || (totalFrames > 0 && currentFrame >= totalFrames))

                Item {
                    width: parent.width
                    height: parent.height - 80 // Allocate space for controls below

                    Text {
                        anchors.top: parent.top
                        anchors.left: parent.left
                        anchors.margins: 10
                        color: "white"
                        font.pixelSize: 16
                        text: qsTr("Frame: %1 / %2").arg(currentFrame).arg(totalFrames)
                    }

                    VideoOutput {
                        id: videoOutputItem
                        anchors.fill: parent
                        visible: !isOutOfBounds

                        Component.onCompleted: {
                            if (players.length > index) {
                                players[index].videoOutput = videoOutputItem
                            }
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: "black"
                        visible: isOutOfBounds
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        onClicked: {
                            if (players.length > index) {
                                console.log("Video " + (index + 1) + " clicked. Attempting to export frame for: " + videoPaths[index])
                                frameExporter.exportCurrentFrame(players[index], videoPaths[index])
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    color: "white"
                    text: qsTr("Offset: %1 frames").arg(frameOffsets[index])
                }

                Slider {
                    width: parent.width
                    from: -maxFrameOffset
                    to: maxFrameOffset
                    stepSize: 1
                    value: frameOffsets[index]
                    enabled: index > 0

                    onMoved: {
                        var newOffsets = frameOffsets.slice();
                        newOffsets[index] = value;
                        frameOffsets = newOffsets;

                        if (typeof playbackManager !== 'undefined') {
                            playbackManager.updateFrameOffsets(frameOffsets);
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: controlsRect // Added id for anchoring
        anchors.bottom: parent.bottom
        width: parent.width
        height: 80
        color: "black"

        Slider {
            id: progressSlider
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 5
            anchors.rightMargin: 5
            anchors.topMargin: 2
            height: 25

            from: 0
            value: playbackManager.currentFrame
            to: playbackManager.totalFrames
            enabled: players.length > 0 && playbackManager.totalFrames > 0

            onMoved: {
                playbackManager.seek(value)
            }
        }

        RangeSlider {
            id: trimSlider
            anchors.top: progressSlider.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 5
            anchors.rightMargin: 5
            anchors.topMargin: 2
            height: 25
            enabled: players.length > 0 && playbackManager.totalFrames > 0

            from: 0
            to: playbackManager.totalFrames
            first.value: 0
            second.value: to

            onToChanged: {
                if (enabled) {
                    first.value = 0;
                    second.value = to;
                }
            }

        }

        Connections {
            target: trimSlider.first
            function onMoved() {
                if (playbackManager.currentFrame < trimSlider.first.value) {
                    playbackManager.seek(trimSlider.first.value);
                }
            }
        }

        Connections {
            target: trimSlider.second
            function onMoved() {
                if (playbackManager.currentFrame > trimSlider.second.value) {
                    playbackManager.seek(trimSlider.second.value);
                }
            }
        }

        Row {
            anchors.top: trimSlider.bottom
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 10
            anchors.topMargin: 3
            anchors.bottomMargin: 2

            Button {
                id: playPauseButton
                text: (typeof playbackManager !== 'undefined' && playbackManager.isPlaying) ? qsTr("Pause") : qsTr("Play")
                enabled: players.length > 0 && !isExporting && (typeof playbackManager !== 'undefined' && playbackManager.totalFrames > 0)

                onClicked: {
                    if (typeof playbackManager !== 'undefined') {
                        playbackManager.togglePlayPause()
                    }
                }
            }

            Button {
                id: saveButton
                text: qsTr("Save Synced")
                enabled: !isExporting && videoInfoProvider.frameRate > 0 && players.length > 0
                ToolTip.text: enabled ? "" : (players.length === 0 ? "No videos loaded" : (videoInfoProvider.frameRate <= 0 ? "Frame rate not available" : "Export in progress"))
                ToolTip.visible: saveButton.hovered && !saveButton.enabled

                onClicked: {
                    console.log("Save Synced clicked.")
                    videoProcessor.exportSyncedVideos(videoPaths, frameOffsets, videoInfoProvider.frameRate, trimSlider.first.value, trimSlider.second.value)
                }
            }

            Button {
                id: saveSequenceButton
                text: qsTr("Save Synced Sequence")
                enabled: !isExporting && videoInfoProvider.frameRate > 0 && players.length > 0
                ToolTip.text: enabled ? "" : (players.length === 0 ? "No videos loaded" : (videoInfoProvider.frameRate <= 0 ? "Frame rate not available" : "Export in progress"))
                ToolTip.visible: saveSequenceButton.hovered && !saveSequenceButton.enabled

                onClicked: {
                    console.log("Save Synced Sequence clicked.")
                    videoProcessor.exportSyncedImageSequence(videoPaths, frameOffsets, videoInfoProvider.frameRate, trimSlider.first.value, trimSlider.second.value)
                }
            }
        }
    }
}
