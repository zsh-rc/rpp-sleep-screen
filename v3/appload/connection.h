#pragma once

#include "../dashboard.h"
#include <QSocketNotifier>

namespace AppLoadProtocol {
constexpr int requestState = 1;
constexpr int requestRefresh = 2;
constexpr int requestReload = 3;
constexpr int stateMessage = 101;
constexpr int newCoordinator = -2;
constexpr int terminateMessage = -1;
constexpr int maxMessage = 16384;

struct Header {
    int type;
    int length;
};
static_assert(sizeof(Header) == 8);

class Connection : public QObject {
public:
    Connection(int fd, Dashboard &dashboard, QString target);
    ~Connection() override;

private:
    void disconnectBackend(const QString &reason);
    void receive();
    void publish();

    int m_fd;
    Dashboard &m_dashboard;
    QString m_target;
    QSocketNotifier m_notifier;
    Header m_header{};
    bool m_haveHeader = false;
    bool m_disconnected = false;
};
}
