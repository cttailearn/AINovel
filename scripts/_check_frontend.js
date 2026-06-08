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
  'components/EnrichmentWorkbench.jsx',
  'components/KnowledgeGraphPanel.jsx',
  'components/NovelReader.jsx',
  'components/Workbench.jsx',
  'components/enrichment/SplitView.jsx',
  'components/enrichment/SummaryView.jsx',
  'components/enrichment/EnrichmentSidePanel.jsx',
  'components/enrichment/HighlightedReader.jsx',
  'components/enrichment/SuggestionHistoryModal.jsx',
  'components/enrichment/EditableField.jsx',
  'components/enrichment/ContextPreview.jsx',
  'components/enrichment/MergedReader.jsx',
  'components/enrichment/SideBySideReader.jsx',
  'components/enrichment/EnrichmentOverview.jsx',
  'utils/textDiffUtil.js',
  'utils/paragraphDiff.js',
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