import socket
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 5555)); srv.listen(1)
while True:
    c, _ = srv.accept(); c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while (d := c.recv(65536)):
        c.sendall(d)
