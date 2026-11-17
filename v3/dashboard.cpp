#include "dashboard.h"

#include <QBuffer>
#include <QCryptographicHash>
#include <QDebug>
#include <QFile>
#include <QFileInfo>
#include <QImageReader>
#include <QProcessEnvironment>
#include <utility>

DashboardImageProvider::DashboardImageProvider() : QQuickImageProvider(QQuickImageProvider::Image) {}

QImage DashboardImageProvider::requestImage(const QString &, QSize *size, const QSize &) {
    if (size) {
        *size = image.size();
    }
    return image;
}

Dashboard::Dashboard(QString targetPath, QString updaterPath, DashboardImageProvider *provider,
                     QObject *parent)
    : QObject(parent), m_targetPath(std::move(targetPath)),
      m_updaterPath(std::move(updaterPath)), m_provider(provider) {
    m_process.setProcessChannelMode(QProcess::MergedChannels);
    connect(&m_process, &QProcess::readyReadStandardOutput, this, &Dashboard::readOutput);
    connect(&m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            m_busy = false;
            setStatus("Cannot start updater: " + m_process.errorString());
        }
    });
    connect(&m_process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this](int code, QProcess::ExitStatus exitStatus) {
        readOutput();
        m_busy = false;
        const auto lines = QString::fromUtf8(m_output).split('\n');
        if (exitStatus == QProcess::NormalExit && code == 75 &&
            lines.contains("RPP_STATUS=busy")) {
            setStatus("The timer is updating the dashboard. Try Refresh again shortly.");
        } else if (exitStatus != QProcess::NormalExit || code != 0) {
            setStatus(QString("Refresh failed (exit %1). Previous preview retained.\n%2")
                          .arg(code).arg(QString::fromUtf8(m_output).trimmed()));
        } else if (lines.contains("RPP_STATUS=updated") || lines.contains("RPP_STATUS=current")) {
            if (loadImage()) {
                setStatus(lines.contains("RPP_STATUS=updated")
                              ? "Downloaded and installed the latest published image."
                              : "Already up to date with GitHub Pages.");
            }
        } else {
            setStatus("Updater returned no supported result. Install the current v2 update.sh.");
        }
    });
    const auto directory = QFileInfo(m_targetPath).absolutePath();
    if (!m_watcher.addPath(directory)) {
        qWarning() << "Cannot watch sleep image directory:" << directory;
    }
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this] {
        if (!m_busy) {
            reload();
        }
    });
    if (loadImage()) {
        setStatus("Showing the installed sleep image. Refresh checks GitHub Pages.");
    }
}

void Dashboard::setStatus(const QString &status) {
    m_status = status;
    qInfo().noquote() << status;
    emit changed();
}

bool Dashboard::loadImage() {
    QFile file(m_targetPath);
    if (!file.open(QIODevice::ReadOnly)) {
        setStatus("Cannot read sleep image: " + file.errorString());
        return false;
    }
    if (file.size() > 20971520) {
        setStatus("Sleep image exceeds 20 MiB. Previous preview retained.");
        return false;
    }
    const auto bytes = file.readAll();
    if (file.error() != QFileDevice::NoError) {
        setStatus("Cannot read sleep image: " + file.errorString());
        return false;
    }
    const auto checksum = QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
    if (checksum == m_checksum) {
        return true;
    }
    QBuffer buffer;
    buffer.setData(bytes);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer, "PNG");
    if (reader.size() != QSize(1620, 2160)) {
        setStatus("Sleep image is not a 1620 x 2160 PNG. Previous preview retained.");
        return false;
    }
    const QImage image = reader.read();
    if (image.isNull()) {
        setStatus("Sleep image is not a decodable 1620 x 2160 PNG. Previous preview retained.");
        return false;
    }
    m_provider->image = image;
    m_checksum = checksum;
    m_imageSource = QString("image://dashboard/%1").arg(++m_revision);
    emit changed();
    return true;
}

void Dashboard::reload() {
    if (m_busy) {
        return;
    }
    const auto previous = m_checksum;
    if (loadImage() && previous != m_checksum) {
        setStatus("Preview updated from the installed sleep image.");
    }
}

void Dashboard::readOutput() {
    m_output += m_process.readAllStandardOutput();
    if (m_output.size() > 16384) {
        m_output = m_output.right(16384);
    }
}

void Dashboard::refresh() {
    if (m_busy) {
        return;
    }
    if (!QFileInfo::exists(m_updaterPath)) {
        setStatus("Updater not found: " + m_updaterPath);
        return;
    }
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert("REPORT_STATUS", "1");
    environment.insert("CHECK_ONLY", "0");
    // Download tools do not need launcher preload libraries.
    environment.remove("LD_PRELOAD");
    m_process.setProcessEnvironment(environment);
    m_output.clear();
    m_busy = true;
    setStatus("Checking GitHub Pages and downloading if changed...");
    m_process.start("/bin/sh", {m_updaterPath});
}
