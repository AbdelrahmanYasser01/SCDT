const express = require('express');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*', // Allow the Angular app to connect
  }
});

// Mock vehicles data
const vehicles = [
  { id: 'veh_01', x: 0, y: 0, z: 0, speed: 40, directionX: 10, directionY: 5 },
  { id: 'veh_02', x: 500, y: 200, z: 0, speed: 60, directionX: -15, directionY: 10 },
  { id: 'veh_03', x: -300, y: -400, z: 0, speed: 30, directionX: 5, directionY: -8 },
];

io.on('connection', (socket) => {
  console.log(`[+] Client connected: ${socket.id}`);

  // Broadcast traffic frames 10 times a second
  const interval = setInterval(() => {
    vehicles.forEach(v => {
      // Move vehicle
      v.x += v.directionX;
      v.y += v.directionY;
      
      // Simple bounce logic to keep them within a local bounding box (e.g. 2km x 2km)
      if (Math.abs(v.x) > 2000) v.directionX *= -1;
      if (Math.abs(v.y) > 2000) v.directionY *= -1;

      // Emit data matching expected format
      socket.emit('message', {
        id: v.id,
        x: v.x,
        y: v.y,
        z: v.z,
        speed: v.speed
      });
    });
  }, 100);

  socket.on('disconnect', () => {
    console.log(`[-] Client disconnected: ${socket.id}`);
    clearInterval(interval);
  });
});

const PORT = 3000;
server.listen(PORT, () => {
  console.log(`Mock SUMO Socket.IO backend running on http://localhost:${PORT}`);
});
