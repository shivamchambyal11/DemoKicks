const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
// '' means same origin: in production FastAPI will serve both this UI and /api.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const TIMEOUT_MS = 30_000

export const IS_MOCK = USE_MOCK

export function sendMessage(message, sessionId) {
  return USE_MOCK ? mockReply(message, sessionId) : realReply(message, sessionId)
}

async function realReply(message, sessionId) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return await response.json()
  } finally {
    clearTimeout(timer)
  }
}

// ---------------------------------------------------------------- mock backend
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const HANDOFF =
  "I don't know the answer to that, so I'm connecting you to a human agent. " +
  'You can also email support@demokicks.example or use live chat Monday to Friday, 9 AM to 6 PM EST.'

async function mockReply(message, sessionId) {
  await sleep(700 + Math.random() * 600)
  const text = message.toLowerCase()
  const base = {
    session_id: sessionId ?? 'mock-session',
    sources: [],
    route: 'rag',
    needs_human: false,
    reason: null,
  }

  if (text.includes('error')) throw new Error('mock failure') // lets us test the error UI

  if (text.includes('return') || text.includes('refund')) {
    return {
      ...base,
      reply:
        'You can return most items within 30 days of delivery if they are unworn and in the original shoebox. ' +
        'Approved refunds reach your original payment method 5-7 business days after approval.',
      sources: ['Returns & Refunds Policy > Return window', 'Returns & Refunds Policy > Refunds'],
    }
  }
  if (text.includes('order')) {
    return {
      ...base,
      route: 'order_tool',
      reply:
        'Hi Rahul, here is the status of order DK1002:\n\n- TrailBlazer GTX - Olive (US M 11) x1\n\n' +
        'Status: Shipped.\n\nShipped via FedEx on Nov 23, 2026.\n\nTracking number: DKT100200200\n\n' +
        'Estimated delivery: Nov 25, 2026.',
    }
  }
  return { ...base, reply: HANDOFF, needs_human: true, reason: 'low_relevance' }
}