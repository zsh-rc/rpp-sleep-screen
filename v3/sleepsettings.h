#pragma once

#include <QString>

bool configureSleepScreen(const QString &settingsPath, const QString &backupPath,
                          const QString &targetPath, QString *error);
bool restoreSleepScreen(const QString &settingsPath, const QString &backupPath, QString *error);
