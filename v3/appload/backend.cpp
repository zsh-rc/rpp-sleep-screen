#include "connection.h"

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <cerrno>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    if (argc != 2) {
        qCritical() << "Expected an AppLoad socket path";
        return 2;
    }
    const QByteArray path = QFile::encodeName(QString::fromLocal8Bit(argv[1]));
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path.isEmpty() || path.size() >= static_cast<int>(sizeof(address.sun_path))) {
        qCritical() << "Invalid AppLoad socket path";
        return 2;
    }
    std::memcpy(address.sun_path, path.constData(), path.size() + 1);
    const int fd = socket(AF_UNIX, SOCK_SEQPACKET, 0);
    if (fd < 0) {
        qCritical() << "Cannot create AppLoad socket:" << strerror(errno);
        return 1;
    }
    bool connected = false;
    for (int attempt = 0; attempt < 50; ++attempt) {
        if (::connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) == 0) {
            connected = true;
            break;
        }
        if (errno != ENOENT && errno != ECONNREFUSED) break;
        usleep(100000);
    }
    if (!connected) {
        qCritical() << "Cannot connect to AppLoad socket:" << strerror(errno);
        close(fd);
        return 1;
    }
    const QString target = qEnvironmentVariable("TARGET_PATH", "/usr/share/remarkable/suspended.png");
    DashboardImageProvider provider;
    Dashboard dashboard(target, qEnvironmentVariable("UPDATER_PATH",
                        "/home/root/rpp-sleep-screen-v2/update.sh"), &provider);
    AppLoadProtocol::Connection connection(fd, dashboard, target);
    return app.exec();
}
