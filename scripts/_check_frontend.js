// Quick syntax check for the new frontend files.
// 使用 @babel/parser 把 JSX 解析为 AST 即可检查语法错误.
const fs = require('fs');
const path = require('path');

const parser = require(path.join(
  path.resolve(__dirname, '..', 'frontend', 'node_modules'),
  '@babel',
  'parser'
));

const FRONTEND = path.resolve(__dirname, '..', 'frontend', 'src');
const files = [
  'App.jsx',
  'api/client.js',
  'components/EnrichmentPage.jsx',
  'components/EnrichmentWorkbench.jsx',
  'components/enrichment/StepBar5.jsx',
  'components/enrichment/ChapterNav.jsx',
  'components/enrichment/ChapterDetail.jsx',
  'components/enrichment/ProgressSummary.jsx',
];

let ok = true;
for (const rel of files) {
  const p = path.join(FRONTEND, rel);
  const src = fs.readFileSync(p, 'utf-8');
  try {
    parser.parse(src, {
      sourceType: 'module',
      plugins: ['jsx'],
    });
    console.log(`[OK ] ${rel} (${src.length} bytes)`);
  } catch (e) {
    ok = false;
    console.log(`[ERR] ${rel}: ${e.message}`);
  }
}

process.exit(ok ? 0 : 1);