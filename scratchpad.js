const https = require('https');

const url = "https://tiles.arcgis.com/tiles/z2tnIkrLQ2BRzr6P/arcgis/rest/services/Linz_IM/SceneServer/layers/0?f=json";

https.get(url, (res) => {
  let data = '';
  res.on('data', (chunk) => data += chunk);
  res.on('end', () => {
    const json = JSON.parse(data);
    console.log("I3S Layer Details:");
    console.log(`- Layer Type: ${json.layerType}`);
    console.log(`- Extent: ${json.store.extent}`);
    console.log(`- Version: ${json.version}`);
    console.log("Verification successful. The layer URL is valid and accessible.");
  });
}).on("error", (err) => {
  console.log("Error: " + err.message);
});
