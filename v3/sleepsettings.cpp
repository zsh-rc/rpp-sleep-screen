#include "sleepsettings.h"

#include <QFile>
#include <QFileInfo>
#include <QSettings>

namespace {
const QString sleepKey = "SleepScreenPath";

bool syncSettings(QSettings &settings, QString *error) {
    settings.sync();
    if (settings.status() != QSettings::NoError) {
        *error = "Cannot read/write settings: " + settings.fileName();
        return false;
    }
    return true;
}

bool validateBackup(QSettings &backup, QString *error) {
    if (!syncSettings(backup, error)) {
        return false;
    }
    const auto present = backup.value("present").toString();
    if (!backup.contains("path") || (present != "true" && present != "false")) {
        *error = "Cannot read a valid sleep setting backup: " + backup.fileName();
        return false;
    }
    return true;
}
}

bool configureSleepScreen(const QString &settingsPath, const QString &backupPath,
                          const QString &targetPath, QString *error) {
    QSettings settings(settingsPath, QSettings::IniFormat);
    if (!syncSettings(settings, error)) {
        return false;
    }
    if (!QFileInfo::exists(backupPath)) {
        QSettings backup(backupPath, QSettings::IniFormat);
        backup.setValue("present", settings.contains(sleepKey));
        backup.setValue("path", settings.value(sleepKey).toString());
        if (!syncSettings(backup, error)) {
            return false;
        }
    }
    QSettings backup(backupPath, QSettings::IniFormat);
    if (!validateBackup(backup, error)) {
        return false;
    }
    if (!QFile::setPermissions(backupPath, QFile::ReadOwner | QFile::WriteOwner)) {
        *error = "Cannot protect sleep setting backup: " + backupPath;
        return false;
    }
    settings.setValue(sleepKey, targetPath);
    return syncSettings(settings, error);
}

bool restoreSleepScreen(const QString &settingsPath, const QString &backupPath, QString *error) {
    if (!QFileInfo::exists(backupPath)) {
        *error = "Sleep setting backup not found: " + backupPath;
        return false;
    }
    QSettings backup(backupPath, QSettings::IniFormat);
    if (!validateBackup(backup, error)) {
        return false;
    }
    QSettings settings(settingsPath, QSettings::IniFormat);
    if (!syncSettings(settings, error)) {
        return false;
    }
    if (backup.value("present").toBool()) {
        settings.setValue(sleepKey, backup.value("path"));
    } else {
        settings.remove(sleepKey);
    }
    return syncSettings(settings, error);
}
