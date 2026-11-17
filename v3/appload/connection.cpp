#include "connection.h"

#include <QCoreApplication>
#include <QDebug>
#include <QJsonDocument>
#include <QJsonObject>
#include <QUrl>
#include <cstring>
#include <sys/socket.h>
#include <unistd.h>
#include <utility>

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

namespace AppLoadProtocol {
Connection::Connection(int fd, Dashboard &dashboard, QString target)
    : m_fd(fd), m_dashboard(dashboard), m_target(std::move(target)),
      m_notifier(fd, QSocketNotifier::Read, this) {
    connect(&m_notifier, &QSocketNotifier::activated, this, [this] { receive(); });
    connect(&m_dashboard, &Dashboard::changed, this, [this] {
        if (m_disconnected) {
            if (!m_dashboard.busy()) QCoreApplication::quit();
        } else {
            publish();
        }
    });
}

Connection::~Connection() { close(m_fd); }

void Connection::disconnectBackend(const QString &reason) {
    qWarning().noquote() << reason;
    m_notifier.setEnabled(false);
    m_disconnected = true;
    if (!m_dashboard.busy()) QCoreApplication::quit();
}

void Connection::receive() {
    char buffer[maxMessage];
    const auto size = recv(m_fd, buffer, sizeof(buffer), MSG_TRUNC);
    if (size <= 0) {
        disconnectBackend("AppLoad connection closed; waiting for any update to finish.");
        return;
    }
    if (size > maxMessage) {
        disconnectBackend("AppLoad message exceeds the supported size.");
        return;
    }
    if (!m_haveHeader) {
        if (size != sizeof(Header)) {
            disconnectBackend("Invalid AppLoad message header.");
            return;
        }
        std::memcpy(&m_header, buffer, sizeof(Header));
        if (m_header.length <= 0 || m_header.length > maxMessage) {
            disconnectBackend("Invalid AppLoad message length.");
            return;
        }
        m_haveHeader = true;
        return;
    }
    if (size != m_header.length) {
        disconnectBackend("Invalid AppLoad message payload.");
        return;
    }
    m_haveHeader = false;
    switch (m_header.type) {
    case terminateMessage:
        disconnectBackend("AppLoad requested termination.");
        break;
    case newCoordinator:
    case requestState:
        publish();
        break;
    case requestRefresh:
        m_dashboard.refresh();
        break;
    case requestReload:
        m_dashboard.reload();
        publish();
        break;
    default:
        qWarning() << "Ignoring unsupported AppLoad message:" << m_header.type;
    }
}

void Connection::publish() {
    const auto imageUrl = m_dashboard.imageSource().isEmpty()
                              ? QString()
                              : QUrl::fromLocalFile(m_target).toString() +
                                    "?revision=" + m_dashboard.imageSource().section('/', -1);
    const QJsonObject state{{"busy", m_dashboard.busy()},
                            {"status", m_dashboard.status()},
                            {"imageUrl", imageUrl}};
    const QByteArray body = QJsonDocument(state).toJson(QJsonDocument::Compact);
    const Header header{stateMessage, static_cast<int>(body.size())};
    if (send(m_fd, &header, sizeof(header), MSG_NOSIGNAL) != sizeof(header) ||
        send(m_fd, body.constData(), body.size(), MSG_NOSIGNAL) != body.size()) {
        disconnectBackend("Cannot send dashboard state to AppLoad.");
    }
}
}
