import test from 'node:test'
import assert from 'node:assert'
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// Load and transpile the TypeScript logger module
const tsPath = path.join(__dirname, 'logger.ts')
const tsCode = fs.readFileSync(tsPath, 'utf8')
const { outputText } = ts.transpileModule(tsCode, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
})
const module = { exports: {} }
const context = { module, exports: module.exports, process, console, setTimeout, clearTimeout, fetch }
vm.createContext(context)
new vm.Script(outputText, { filename: 'logger.js' }).runInContext(context)
const logger = context.module.exports.logger

function startTestServer() {
  let callCount = 0
  const requests = []
  const server = http.createServer((req, res) => {
    let body = ''
    req.on('data', chunk => (body += chunk))
    req.on('end', () => {
      requests.push(body)
      callCount += 1
      res.statusCode = callCount < 2 ? 500 : 200
      res.end()
    })
  })
  return new Promise(resolve => {
    server.listen(0, () => {
      const address = server.address()
      const port = typeof address === 'string' ? 0 : address.port
      resolve({
        url: `http://localhost:${port}`,
        close: () => server.close(),
        requests,
        callCount: () => callCount
      })
    })
  })
}

test('sendToLoggingService retries and eventually delivers log', async () => {
  const server = await startTestServer()
  process.env.LOGGING_ENDPOINT = server.url
  const entry = { level: 'info', message: 'hello' }
  await logger.sendToLoggingService(entry)
  assert.equal(server.callCount(), 2)
  assert.deepEqual(JSON.parse(server.requests[1]), entry)
  server.close()
})
