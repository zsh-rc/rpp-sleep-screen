#include "../dashboard.h"
#include "../sleepsettings.h"

#include <QFile>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickWindow>
#include <QSettings>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

class DashboardTests : public QObject {
    Q_OBJECT
private:
    static void writeFile(const QString &path, const QByteArray &contents) {
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write(contents), contents.size());
    }

    static void writeImage(const QString &path, Qt::GlobalColor color = Qt::green) {
        QImage image(1620, 2160, QImage::Format_RGB888);
        image.fill(color);
        QVERIFY(image.save(path));
    }

    static QQuickItem *findItem(QQuickItem *parent, const QString &name) {
        if (parent->objectName() == name) {
            return parent;
        }
        for (auto *child : parent->childItems()) {
            if (auto *item = findItem(child, name)) {
                return item;
            }
        }
        return nullptr;
    }

private slots:
    void init() {
        qputenv("LD_PRELOAD", "");
    }

    void previewLoadsAndReloadsAtomicReplacement() {
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        writeImage(target);
        DashboardImageProvider provider;
        Dashboard dashboard(target, dir.filePath("update.sh"), &provider);
        QVERIFY(!dashboard.imageSource().isEmpty());
        QCOMPARE(provider.image.pixelColor(0, 0), QColor(Qt::green));
        const auto source = dashboard.imageSource();
        dashboard.reload();
        QCOMPARE(dashboard.imageSource(), source);
        const auto replacement = dir.filePath("replacement.png");
        writeImage(replacement, Qt::blue);
        QVERIFY(QFile::remove(target));
        QVERIFY(QFile::rename(replacement, target));
        QTRY_COMPARE(provider.image.pixelColor(0, 0), QColor(Qt::blue));
        QVERIFY(dashboard.imageSource() != source);
    }

    void invalidImageKeepsPreviousPreview() {
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        writeImage(target);
        DashboardImageProvider provider;
        Dashboard dashboard(target, dir.filePath("update.sh"), &provider);
        const auto source = dashboard.imageSource();
        writeFile(target, "not a PNG");
        dashboard.reload();
        QCOMPARE(dashboard.imageSource(), source);
        QVERIFY(dashboard.status().contains("Previous preview retained"));
        QImage small(1, 1, QImage::Format_RGB888);
        QVERIFY(small.save(target));
        dashboard.reload();
        QCOMPARE(dashboard.imageSource(), source);
    }

    void missingFilesAreExplicit() {
        QTemporaryDir dir;
        DashboardImageProvider provider;
        Dashboard dashboard(dir.filePath("missing.png"), dir.filePath("missing.sh"), &provider);
        QVERIFY(dashboard.status().contains("Cannot read"));
        dashboard.refresh();
        QVERIFY(dashboard.status().contains("Updater not found"));
        QVERIFY(!dashboard.busy());
    }

    void refreshOutcomes_data() {
        QTest::addColumn<QByteArray>("script");
        QTest::addColumn<QString>("status");
        QTest::newRow("updated") << QByteArray("echo RPP_STATUS=updated\n") << "Downloaded";
        QTest::newRow("current") << QByteArray("echo RPP_STATUS=current\n") << "Already up to date";
        QTest::newRow("busy") << QByteArray("echo RPP_STATUS=busy\nexit 75\n") << "timer is updating";
        QTest::newRow("offline") << QByteArray("echo 'Network unavailable' >&2\nexit 22\n")
                                << "Network unavailable";
        QTest::newRow("cleanup-error") << QByteArray("echo RPP_STATUS=updated\nexit 1\n")
                                      << "Refresh failed";
        QTest::newRow("old-updater") << QByteArray("echo 'Sleep screen updated'\n")
                                    << "no supported result";
    }

    void refreshOutcomes() {
        QFETCH(QByteArray, script);
        QFETCH(QString, status);
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        const auto updater = dir.filePath("update.sh");
        writeImage(target);
        writeFile(updater, script);
        DashboardImageProvider provider;
        Dashboard dashboard(target, updater, &provider);
        dashboard.refresh();
        QVERIFY(dashboard.busy());
        QTRY_VERIFY(!dashboard.busy());
        QVERIFY2(dashboard.status().contains(status), qPrintable(dashboard.status()));
        QCOMPARE(provider.image.pixelColor(0, 0), QColor(Qt::green));
    }

    void refreshPassesProtocolAndDoesNotRunTwice() {
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        const auto updater = dir.filePath("update.sh");
        writeImage(target);
        writeFile(updater, "test \"$REPORT_STATUS\" = 1 || exit 1\n"
                           "test \"$CHECK_ONLY\" = 0 || exit 2\n"
                           "test -z \"$LD_PRELOAD\" || exit 3\n"
                           "sleep 0.1\necho RPP_STATUS=current\n");
        DashboardImageProvider provider;
        Dashboard dashboard(target, updater, &provider);
        QSignalSpy changed(&dashboard, &Dashboard::changed);
        dashboard.refresh();
        const auto count = changed.count();
        dashboard.refresh();
        QCOMPARE(changed.count(), count);
        QTRY_VERIFY(!dashboard.busy());
        QVERIFY(dashboard.status().contains("Already up to date"));
    }

    void successfulDownloadImmediatelyReplacesPreview() {
        QTemporaryDir dir;
        const auto target = dir.filePath("suspended.png");
        const auto next = dir.filePath("next.png");
        const auto updater = dir.filePath("update.sh");
        writeImage(target);
        writeImage(next, Qt::blue);
        writeFile(updater, ("cp '" + next + "' '" + target +
                           "'\necho RPP_STATUS=updated\n").toUtf8());
        DashboardImageProvider provider;
        Dashboard dashboard(target, updater, &provider);
        const auto source = dashboard.imageSource();
        dashboard.refresh();
        QTRY_VERIFY(!dashboard.busy());
        QCOMPARE(provider.image.pixelColor(0, 0), QColor(Qt::blue));
        QVERIFY(dashboard.imageSource() != source);
    }

    void sleepSettingUsesGeneralSectionAndRestoresOnlyItsKey() {
        QTemporaryDir dir;
        const auto settings = dir.filePath("xochitl.conf");
        const auto backup = dir.filePath("backup.ini");
        writeFile(settings, "[General]\nSleepScreenPath=/original.png\nOtherSetting=keep\n");
        QString error;
        QVERIFY2(configureSleepScreen(settings, backup, "/suspended.png", &error), qPrintable(error));
        QSettings check(settings, QSettings::IniFormat);
        QCOMPARE(check.value("SleepScreenPath").toString(), QString("/suspended.png"));
        QCOMPARE(check.value("OtherSetting").toString(), QString("keep"));
        QVERIFY(!check.contains("General/SleepScreenPath"));
        QVERIFY(configureSleepScreen(settings, backup, "/suspended.png", &error));
        QVERIFY(restoreSleepScreen(settings, backup, &error));
        check.sync();
        QCOMPARE(check.value("SleepScreenPath").toString(), QString("/original.png"));
        QCOMPARE(check.value("OtherSetting").toString(), QString("keep"));
    }

    void absentSleepSettingIsRemovedOnRestore() {
        QTemporaryDir dir;
        const auto settings = dir.filePath("xochitl.conf");
        const auto backup = dir.filePath("backup.ini");
        QString error;
        QVERIFY(configureSleepScreen(settings, backup, "/suspended.png", &error));
        QVERIFY(restoreSleepScreen(settings, backup, &error));
        QSettings check(settings, QSettings::IniFormat);
        QVERIFY(!check.contains("SleepScreenPath"));
        QVERIFY(!restoreSleepScreen(settings, dir.filePath("missing.ini"), &error));
        QVERIFY(error.contains("not found"));
    }

    void invalidBackupPreventsSettingsChange() {
        QTemporaryDir dir;
        const auto settings = dir.filePath("xochitl.conf");
        const auto backup = dir.filePath("backup.ini");
        writeFile(settings, "[General]\nSleepScreenPath=/original.png\n");
        writeFile(backup, "[General]\ninvalid=backup\n");
        QString error;
        QVERIFY(!configureSleepScreen(settings, backup, "/suspended.png", &error));
        writeFile(backup, "[General]\npresent=invalid\npath=/original.png\n");
        QVERIFY(!configureSleepScreen(settings, backup, "/suspended.png", &error));
        QVERIFY(!restoreSleepScreen(settings, backup, &error));
        QSettings check(settings, QSettings::IniFormat);
        QCOMPARE(check.value("SleepScreenPath").toString(), QString("/original.png"));
    }

    void qmlLoadsWithoutErrors() {
        QTemporaryDir dir;
        writeImage(dir.filePath("suspended.png"));
        writeImage(dir.filePath("next.png"), Qt::blue);
        writeFile(dir.filePath("update.sh"),
                  ("cp '" + dir.filePath("next.png") + "' '" +
                   dir.filePath("suspended.png") + "'\necho RPP_STATUS=updated\n").toUtf8());
        auto *provider = new DashboardImageProvider;
        Dashboard dashboard(dir.filePath("suspended.png"), dir.filePath("update.sh"), provider);
        QQmlApplicationEngine engine;
        engine.addImageProvider("dashboard", provider);
        engine.rootContext()->setContextProperty("dashboard", &dashboard);
        QSignalSpy warnings(&engine, &QQmlEngine::warnings);
        engine.load(QUrl("qrc:/Main.qml"));
        QCOMPARE(engine.rootObjects().size(), 1);
        QTest::qWait(100);
        QCOMPARE(warnings.count(), 0);
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        QVERIFY(window);
        auto *controls = findItem(window->contentItem(), "controls");
        auto *fullScreen = findItem(window->contentItem(), "button-Full screen");
        QVERIFY(controls);
        QVERIFY(fullScreen);
        QVERIFY(controls->isVisible());
        const auto center = fullScreen->mapToScene(
            QPointF(fullScreen->width() / 2, fullScreen->height() / 2)).toPoint();
        QTest::mouseClick(window, Qt::LeftButton, Qt::NoModifier, center);
        QVERIFY(!controls->isVisible());
        QTest::mouseClick(window, Qt::LeftButton, Qt::NoModifier, QPoint(20, 20));
        QVERIFY(controls->isVisible());
        auto *refresh = findItem(window->contentItem(), "button-Refresh");
        QVERIFY(refresh);
        QTest::mouseClick(window, Qt::LeftButton, Qt::NoModifier,
                          refresh->mapToScene(QPointF(refresh->width() / 2,
                                                     refresh->height() / 2)).toPoint());
        QTRY_VERIFY(!dashboard.busy());
        QVERIFY(dashboard.status().contains("Downloaded"));
        QTest::qWait(100);
        const auto frame = window->grabWindow();
        QVERIFY(!frame.isNull());
        QCOMPARE(frame.pixelColor(frame.width() / 2, frame.height() / 3), QColor(Qt::blue));
        const auto screenshot = qEnvironmentVariable("V3_SCREENSHOT_PATH");
        if (!screenshot.isEmpty()) {
            QVERIFY(frame.save(screenshot));
        }
    }
};

QTEST_MAIN(DashboardTests)
#include "test_dashboard.moc"
