const dgram = require('dgram');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*',
  }
});

// Socket.IO server on port 3000
io.on('connection', (socket) => {
  console.log(`[+] Client connected: ${socket.id}`);
  socket.on('disconnect', () => {
    console.log(`[-] Client disconnected: ${socket.id}`);
  });
});

const PORT = 3000;
server.listen(PORT, () => {
  console.log(`WebSocket Bridge running on http://localhost:${PORT}`);
});

// UDP Listener on port 5005
const udpServer = dgram.createSocket('udp4');

udpServer.on('error', (err) => {
  console.error(`UDP Server error:\n${err.stack}`);
  udpServer.close();
});

udpServer.on('message', (msg, rinfo) => {
  try {
    const payload = JSON.parse(msg.toString());
    
    // Check if it's a vehicle frame
    if (payload.vehicles && Array.isArray(payload.vehicles)) {
      payload.vehicles.forEach(v => {
        // Broadcast the specific format expected by Angular MapComponent
        io.emit('message', {
          id: v.id,
          x: v.x,
          y: v.y,
          z: v.z,
          speed: v.speed
        });
      });
    }
  } catch (e) {
    console.error("Failed to parse UDP packet:", e);
  }
});

udpServer.on('listening', () => {
  const address = udpServer.address();
  console.log(`UDP Server listening for SUMO telemetry on ${address.address}:${address.port}`);
});

// Start UDP Listener
udpServer.bind(5005);
