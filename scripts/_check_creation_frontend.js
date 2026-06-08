// Quick syntax check for new creation frontend components
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const FRONTEND = path.join(__dirname, '..', 'frontend', 'src', 'components', 'creation');
const APP_JSX = path.join(__dirname, '..', 'frontend', 'src', 'App.jsx');
const CLIENT_JS = path.join(__dirname, '..', 'frontend', 'src', 'api', 'client.js');

const files = [
  APP_JSX,
  CLIENT_JS,
  path.join(FRONTEND, 'creation.css'),
  path.join(FRONTEND, 'CreationStudio.jsx'),
  path.join(FRONTEND, 'ProjectForm.jsx'),
  path.join(FRONTEND, 'ChapterList.jsx'),
  path.join(FRONTEND, 'ChapterGenerator.jsx'),
  path.join(FRONTEND, 'VariantCards.jsx'),
  path.join(FRONTEND, 'VariantEditor.jsx'),
  path.join(FRONTEND, 'ProjectKGPreview.jsx'),
];

let failed = 0;
for (const f of files) {
  if (!fs.existsSync(f)) {
    console.log(`MISSING ${path.relative(path.join(__dirname, '..'), f)}`);
    failed++;
    continue;
  }
  console.log(`OK   ${path.relative(path.join(__dirname, '..'), f)}`);
}
if (failed) {
  console.log(`\n${failed} file(s) missing`);
  process.exit(1);
}
console.log('\nAll frontend files present');

// Quick parse of JSX with babel
try {
  console.log('\n=== Babel parse check (JSX) ===');
  const babel = require(path.join(__dirname, '..', 'frontend', 'node_modules', '@babel', 'parser'));
  for (const f of files.filter((p) => p.endsWith('.jsx') || p.endsWith('.js'))) {
    const src = fs.readFileSync(f, 'utf-8');
    try {
      babel.parse(src, { sourceType: 'module', plugins: ['jsx'] });
      console.log(`OK   ${path.relative(path.join(__dirname, '..'), f)}`);
    } catch (e) {
      console.log(`FAIL ${path.relative(path.join(__dirname, '..'), f)}: ${e.message}`);
      failed++;
    }
  }
} catch (e) {
  console.log('(skip babel check, parser not found:', e.message, ')');
}
if (failed) {
  console.log(`\n${failed} parse error(s)`);
  process.exit(1);
}
console.log('\n=== ALL FRONTEND FILES PARSE OK ===');
