#pragma once

#include <QFileSystemWatcher>
#include <QImage>
#include <QObject>
#include <QProcess>
#include <QQuickImageProvider>

class DashboardImageProvider : public QQuickImageProvider {
public:
    DashboardImageProvider();
    QImage requestImage(const QString &id, QSize *size, const QSize &requestedSize) override;
    QImage image;
};

class Dashboard : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(QString status READ status NOTIFY changed)
    Q_PROPERTY(QString imageSource READ imageSource NOTIFY changed)

public:
    Dashboard(QString targetPath, QString updaterPath, DashboardImageProvider *provider,
              QObject *parent = nullptr);
    bool busy() const { return m_busy; }
    QString status() const { return m_status; }
    QString imageSource() const { return m_imageSource; }
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void reload();

signals:
    void changed();

private:
    bool loadImage();
    void setStatus(const QString &status);
    void readOutput();
    QString m_targetPath;
    QString m_updaterPath;
    DashboardImageProvider *m_provider;
    QFileSystemWatcher m_watcher;
    QProcess m_process;
    QByteArray m_output;
    QByteArray m_checksum;
    QString m_imageSource;
    QString m_status;
    bool m_busy = false;
    quint64 m_revision = 0;
};
