import QtQuick
import QtQuick.Window

Window {
    id: window
    width: 1620
    height: 2160
    visible: true
    visibility: Window.FullScreen
    color: "white"
    title: "Dashboard"
    property bool controlsVisible: true

    onActiveChanged: {
        if (active) dashboard.reload()
    }
    onClosing: function(close) {
        if (dashboard.busy) {
            close.accepted = false
            controlsVisible = true
        }
    }

    Image {
        anchors.fill: parent
        source: dashboard.imageSource
        fillMode: Image.PreserveAspectFit
        cache: false
        asynchronous: false
    }

    MouseArea {
        anchors.fill: parent
        onClicked: window.controlsVisible = !window.controlsVisible
    }

    Rectangle {
        id: controls
        objectName: "controls"
        visible: window.controlsVisible || dashboard.busy
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.max(220, statusText.implicitHeight + 140)
        color: "white"
        border.color: "black"
        border.width: 2

        Text {
            id: statusText
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 24
            text: dashboard.status
            font.pixelSize: Math.max(20, window.width / 60)
            color: "black"
            wrapMode: Text.Wrap
            maximumLineCount: 4
            elide: Text.ElideRight
        }

        Row {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottomMargin: 20
            spacing: 24

            Repeater {
                model: ["Refresh", "Full screen", "Back"]
                delegate: Rectangle {
                    required property string modelData
                    objectName: "button-" + modelData
                    width: Math.min(360, (window.width - 96) / 3)
                    height: 80
                    color: dashboard.busy ? "#dddddd" : "white"
                    border.width: 2
                    border.color: "black"
                    Text {
                        anchors.centerIn: parent
                        text: modelData
                        color: "black"
                        font.pixelSize: Math.max(20, window.width / 54)
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: !dashboard.busy
                        onClicked: {
                            if (modelData === "Refresh") dashboard.refresh()
                            else if (modelData === "Back") Qt.quit()
                            else window.controlsVisible = false
                        }
                    }
                }
            }
        }
    }
}
