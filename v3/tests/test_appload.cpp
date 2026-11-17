#include "../appload/connection.h"

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQmlApplicationEngine>
#include <QQuickItem>
#include <QQuickWindow>
#include <QResource>
#include <QTemporaryDir>
#include <QTest>
#include <QtQml>
#include <sys/socket.h>
#include <unistd.h>

using namespace AppLoadProtocol;

class MockEndpoint : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString applicationID MEMBER applicationID)
public:
    QString applicationID;
    int lastType = 0;
    Q_INVOKABLE void sendMessage(int type, const QString &) { lastType = type; }
    Q_INVOKABLE void terminate() {}
signals:
    void messageReceived(int type, const QString &contents);
};

class AppLoadTests : public QObject {
    Q_OBJECT
private:
    static int socketKind() {
#ifdef __linux__
        return SOCK_SEQPACKET;
#else
        return SOCK_DGRAM;
#endif
    }

    static QQuickItem *findItem(QQuickItem *parent, const QString &name) {
        if (parent->objectName() == name) return parent;
        for (auto *child : parent->childItems()) {
            if (auto *item = findItem(child, name)) return item;
        }
        return nullptr;
    }
    static void sendPacket(int fd, int type, const QByteArray &body) {
        Header header{type, static_cast<int>(body.size())};
        QCOMPARE(send(fd, &header, sizeof(header), 0), ssize_t(sizeof(header)));
        QCOMPARE(send(fd, body.constData(), body.size(), 0), ssize_t(body.size()));
    }

    static QJsonObject readState(int fd) {
        Header header{};
        const auto size = recv(fd, &header, sizeof(header), MSG_DONTWAIT);
        if (size != sizeof(header)) return {};
        if (header.type != stateMessage || header.length <= 0 || header.length > maxMessage) return {};
        QByteArray body(header.length, '\0');
        if (recv(fd, body.data(), body.size(), 0) != body.size()) return {};
        return QJsonDocument::fromJson(body).object();
    }

private slots:
    void protocolRefreshAndReload() {
        QTemporaryDir dir;
        const QString target = dir.filePath("suspended.png");
        const QString next = dir.filePath("next.png");
        const QString updater = dir.filePath("update.sh");
        QImage first(1620, 2160, QImage::Format_RGB888);
        first.fill(Qt::green);
        QVERIFY(first.save(target));
        first.fill(Qt::blue);
        QVERIFY(first.save(next));
        QFile script(updater);
        QVERIFY(script.open(QIODevice::WriteOnly));
        script.write(("sleep 0.1\ncp '" + next + "' '" + target +
                      "'\necho RPP_STATUS=updated\n").toUtf8());
        script.close();

        int fds[2];
        QCOMPARE(socketpair(AF_UNIX, socketKind(), 0, fds), 0);
        DashboardImageProvider provider;
        Dashboard dashboard(target, updater, &provider);
        Connection connection(fds[0], dashboard, target);

        sendPacket(fds[1], requestState, "state");
        QJsonObject state;
        QTRY_VERIFY(!state.isEmpty() || !(state = readState(fds[1])).isEmpty());
        QVERIFY(state.value("status").toString().contains("Showing"));
        QVERIFY(state.value("imageUrl").toString().startsWith("file:"));
        const QString previous = state.value("imageUrl").toString();

        sendPacket(fds[1], requestRefresh, "refresh");
        QTRY_VERIFY(dashboard.busy());
        QTRY_VERIFY(!dashboard.busy());
        QCOMPARE(provider.image.pixelColor(0, 0), QColor(Qt::blue));
        QJsonObject current;
        QTRY_VERIFY(!current.isEmpty() || !(current = readState(fds[1])).isEmpty());
        while (true) {
            const auto nextState = readState(fds[1]);
            if (nextState.isEmpty()) break;
            current = nextState;
        }
        QVERIFY(current.value("status").toString().contains("Downloaded"));
        QVERIFY(current.value("imageUrl").toString() != previous);

        sendPacket(fds[1], requestReload, "reload");
        QJsonObject reloaded;
        QTRY_VERIFY(!reloaded.isEmpty() || !(reloaded = readState(fds[1])).isEmpty());
        close(fds[1]);
    }

    void socketRejectsInvalidHeader() {
        QTemporaryDir dir;
        int fds[2];
        QCOMPARE(socketpair(AF_UNIX, socketKind(), 0, fds), 0);
        DashboardImageProvider provider;
        Dashboard dashboard(dir.filePath("missing.png"), dir.filePath("missing.sh"), &provider);
        Connection connection(fds[0], dashboard, dir.filePath("missing.png"));
        const QByteArray invalid("invalid");
        QCOMPARE(send(fds[1], invalid.data(), invalid.size(), 0), ssize_t(invalid.size()));
        QTest::qWait(50);
        close(fds[1]);
    }

    void terminationWaitsForUpdate() {
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        const auto updater = dir.filePath("update.sh");
        QImage image(1620, 2160, QImage::Format_RGB888);
        image.fill(Qt::green);
        QVERIFY(image.save(target));
        QFile script(updater);
        QVERIFY(script.open(QIODevice::WriteOnly));
        script.write("sleep 0.2\necho RPP_STATUS=current\n");
        script.close();
        int fds[2];
        QCOMPARE(socketpair(AF_UNIX, socketKind(), 0, fds), 0);
        DashboardImageProvider provider;
        Dashboard dashboard(target, updater, &provider);
        Connection connection(fds[0], dashboard, target);
        sendPacket(fds[1], requestRefresh, "refresh");
        QTRY_VERIFY(dashboard.busy());
        sendPacket(fds[1], terminateMessage, "close");
        QTRY_VERIFY(!dashboard.busy());
        QVERIFY(dashboard.status().contains("Already up to date"));
        close(fds[1]);
    }

    void qmlDisplaysLocalImageAndSendsRefresh() {
        QTemporaryDir dir;
        QImage image(1620, 2160, QImage::Format_RGB888);
        image.fill(Qt::blue);
        const auto path = dir.filePath("suspended.png");
        QVERIFY(image.save(path));
        qmlRegisterType<MockEndpoint>("net.asivery.AppLoad", 1, 0, "AppLoad");
        QVERIFY(QResource::registerResource(APPLOAD_RESOURCE_PATH));
        QQmlApplicationEngine engine;
        engine.load(QUrl("qrc:/ui/Dashboard.qml"));
        QCOMPARE(engine.rootObjects().size(), 1);
        auto *root = qobject_cast<QQuickItem *>(engine.rootObjects().first());
        QVERIFY(root);
        QQuickWindow window;
        window.resize(800, 1000);
        root->setParentItem(window.contentItem());
        root->setWidth(800);
        root->setHeight(1000);
        window.show();
        auto *endpoint = root->findChild<MockEndpoint *>();
        QVERIFY(endpoint);
        QJsonObject state{{"busy", false}, {"status", "Image ready"},
                          {"imageUrl", QUrl::fromLocalFile(path).toString() + "?revision=1"}};
        emit endpoint->messageReceived(101, QString::fromUtf8(
            QJsonDocument(state).toJson(QJsonDocument::Compact)));
        QTRY_VERIFY(root->property("connected").toBool());
        QTRY_VERIFY(!window.grabWindow().isNull());
        QTest::qWait(100);
        const auto frame = window.grabWindow();
        QCOMPARE(frame.pixelColor(frame.width() / 2, frame.height() / 3), QColor(Qt::blue));
        auto *refresh = findItem(root, "button-Refresh");
        QVERIFY(refresh);
        QTest::mouseClick(&window, Qt::LeftButton, Qt::NoModifier,
                          refresh->mapToScene(QPointF(refresh->width() / 2,
                                                     refresh->height() / 2)).toPoint());
        QCOMPARE(endpoint->lastType, requestRefresh);
        root->setParentItem(nullptr);
    }
};

QTEST_MAIN(AppLoadTests)
#include "test_appload.moc"
