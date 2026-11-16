#include "dashboard.h"
#include "sleepsettings.h"

#include <QCoreApplication>
#include <QDebug>
#include <QDir>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>

int main(int argc, char *argv[]) {
    const QString target = qEnvironmentVariable("TARGET_PATH", "/usr/share/remarkable/suspended.png");
    if (argc == 2 && (QString(argv[1]) == "--configure-sleep-screen" ||
                      QString(argv[1]) == "--restore-sleep-screen")) {
        QCoreApplication app(argc, argv);
        const auto home = QDir::homePath();
        const auto settings = home + "/.config/remarkable/xochitl.conf";
        const auto backup = QCoreApplication::applicationDirPath() + "/sleep-setting-backup.ini";
        QString error;
        const bool success = QString(argv[1]) == "--configure-sleep-screen"
                                 ? configureSleepScreen(settings, backup, target, &error)
                                 : restoreSleepScreen(settings, backup, &error);
        if (!success) {
            qCritical().noquote() << error;
            return 1;
        }
        qInfo() << "Sleep setting saved. Restart Oxide before testing sleep.";
        return 0;
    }

    QGuiApplication app(argc, argv);
    auto *provider = new DashboardImageProvider;
    Dashboard dashboard(target, qEnvironmentVariable("UPDATER_PATH",
                        "/home/root/rpp-sleep-screen-v2/update.sh"), provider);
    QQmlApplicationEngine engine;
    engine.addImageProvider("dashboard", provider);
    engine.rootContext()->setContextProperty("dashboard", &dashboard);
    engine.load(QUrl("qrc:/Main.qml"));
    if (engine.rootObjects().isEmpty()) {
        return 1;
    }
    return app.exec();
}
