const http = require('http');
const fs = require('fs');
const path = require('path');

const server = http.createServer((req, res) => {
  let urlPath = req.url === '/' ? '/report.html' : req.url;
  const filePath = path.join(__dirname, urlPath);
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain;charset=utf-8' });
      res.end('Not found: ' + urlPath);
      return;
    }
    const ext = path.extname(filePath);
    const ct = ext === '.html' ? 'text/html;charset=utf-8'
             : ext === '.js'   ? 'application/javascript'
             : ext === '.json' ? 'application/json'
             : ext === '.css'  ? 'text/css'
             : 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': ct, 'Cache-Control': 'no-cache' });
    res.end(data);
  });
});

server.listen(8766, '127.0.0.1', () => {
  console.log('600967 server ready on http://localhost:8766');
});