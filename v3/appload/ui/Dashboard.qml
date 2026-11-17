import QtQuick
import net.asivery.AppLoad 1.0

Rectangle {
    objectName: "controls"
    id: root
    color: "white"
    signal close
    property bool controlsVisible: true
    property bool busy: false
    property bool connected: false
    property string status: "Connecting to dashboard backend..."
    property string imageUrl: ""
    property int attempts: 0

    function unloading() {
        // Keep the backend alive until a running updater has completed.
    }

    AppLoad {
        id: endpoint
        applicationID: "rpp-dashboard-v3"
        onMessageReceived: function(type, contents) {
            if (type !== 101) return
            try {
                let state = JSON.parse(contents)
                root.connected = true
                root.busy = state.busy
                root.status = state.status
                if (state.imageUrl !== root.imageUrl) root.imageUrl = state.imageUrl
            } catch (error) {
                root.status = "Invalid response from dashboard backend: " + error
            }
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: !root.connected && root.attempts < 10
        triggeredOnStart: true
        onTriggered: {
            root.attempts++
            endpoint.sendMessage(1, "state")
            if (root.attempts === 10 && !root.connected)
                root.status = "Cannot connect to dashboard backend. Close and reopen the app."
        }
    }

    Image {
        anchors.fill: parent
        source: root.imageUrl
        fillMode: Image.PreserveAspectFit
        cache: false
        onStatusChanged: {
            if (status === Image.Error)
                root.status = "Cannot display the installed sleep image."
        }
    }
    MouseArea {
        anchors.fill: parent
        onClicked: root.controlsVisible = !root.controlsVisible
    }
    Rectangle {
        visible: root.controlsVisible || root.busy
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
            text: root.status
            font.pixelSize: Math.max(20, root.width / 60)
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
                    width: Math.min(360, (root.width - 96) / 3)
                    height: 80
                    color: root.busy ? "#dddddd" : "white"
                    border.width: 2
                    border.color: "black"
                    Text {
                        anchors.centerIn: parent
                        text: modelData
                        color: "black"
                        font.pixelSize: Math.max(20, root.width / 54)
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: !root.busy && (root.connected || modelData !== "Refresh")
                        onClicked: {
                            if (modelData === "Refresh") endpoint.sendMessage(2, "refresh")
                            else if (modelData === "Back") root.close()
                            else root.controlsVisible = false
                        }
                    }
                }
            }
        }
    }
}
