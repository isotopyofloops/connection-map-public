#!/usr/bin/env node
const cytoscape = require('cytoscape');
const fs = require('fs');

const data = JSON.parse(fs.readFileSync('graph-data.json', 'utf8'));

const elements = [];
const nodeIds = new Set();
for (const n of data.nodes) {
  nodeIds.add(n.id);
  elements.push({ data: { id: n.id } });
}
for (const e of data.edges) {
  if (e.predicate === 'cosine_similarity') continue;
  if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
  elements.push({ data: { source: e.source, target: e.target } });
}

console.log(`Computing cose layout for ${data.nodes.length} nodes...`);
const start = Date.now();

const cy = cytoscape({
  elements,
  headless: true,
  styleEnabled: false,
});

cy.layout({
  name: 'cose',
  animate: false,
  nodeRepulsion: function() { return 500000; },
  idealEdgeLength: function() { return 90; },
  gravity: 0.4,
  numIter: 300,
  randomize: true,
  fit: true,
  padding: 30,
  stop: function() {
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`Layout complete in ${elapsed}s`);

    for (const n of data.nodes) {
      const cyNode = cy.getElementById(n.id);
      if (cyNode.length) {
        const pos = cyNode.position();
        n.x = Math.round(pos.x * 100) / 100;
        n.y = Math.round(pos.y * 100) / 100;
      }
    }

    fs.writeFileSync('graph-data.json', JSON.stringify(data));
    console.log('Positions written to graph-data.json');
  }
}).run();
