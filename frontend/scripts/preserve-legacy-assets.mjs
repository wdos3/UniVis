import { copyFileSync, readFileSync } from 'node:fs'

const html = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')
const currentScript = html.match(/<script[^>]+src="(\/assets\/index-[^"]+\.js)"/)?.[1]
const currentStyle = html.match(/<link[^>]+href="(\/assets\/index-[^"]+\.css)"/)?.[1]

if (!currentScript || !currentStyle) {
  throw new Error('Could not locate the built app entrypoints in index.html')
}

// A prior deployment's HTML was cached by some browsers after its hashed assets
// disappeared. Keep those entrypoint URLs working while HTML caching is disabled.
for (const [legacyName, currentPath] of [
  ['index-2otZwEKJ.js', currentScript],
  ['index-xa4c_WTv.css', currentStyle],
]) {
  copyFileSync(
    new URL(`../dist${currentPath}`, import.meta.url),
    new URL(`../dist/assets/${legacyName}`, import.meta.url),
  )
}
