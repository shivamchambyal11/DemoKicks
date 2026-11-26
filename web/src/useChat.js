import { useCallback, useRef, useState } from 'react'
import { sendMessage } from './api'

const SESSION_KEY = 'demokicks.sessionId'

const WELCOME = {
  id: 'welcome',
  role: 'assistant',
  text:
    "Hi! I'm the DemoKicks assistant. I can answer questions about returns, shipping, " +
    'sizing and warranty, and check your order status. How can I help?',
  sources: [],
}

let idCounter = 0
const nextId = (prefix) => `${prefix}${idCounter++}`

// Storage can be blocked (private mode, third-party iframes): never let that break the chat.
function readSessionId() {
  try {
    return sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}
function writeSessionId(id) {
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id)
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* ignore */
  }
}

export function useChat() {
  const [messages, setMessages] = useState([WELCOME])
  const [isLoading, setIsLoading] = useState(false)
  // Refs hold values that must not trigger a re-render.
  const sessionId = useRef(readSessionId())
  const busy = useRef(false) // guards against double submit (fast double Enter)

  const send = useCallback(async (rawText) => {
    const text = rawText.trim()
    if (!text || busy.current) return
    busy.current = true
    setIsLoading(true)
    setMessages((prev) => [...prev, { id: nextId('u'), role: 'user', text }])

    try {
      const data = await sendMessage(text, sessionId.current)
      if (data.session_id && data.session_id !== sessionId.current) {
        sessionId.current = data.session_id
        writeSessionId(data.session_id)
      }
      setMessages((prev) => [
        ...prev,
        {
          id: nextId('a'),
          role: 'assistant',
          text: data.reply,
          sources: data.sources ?? [],
          needsHuman: Boolean(data.needs_human),
        },
      ])
    } catch (error) {
      console.error('Chat request failed:', error)
      setMessages((prev) => [
        ...prev,
        {
          id: nextId('e'),
          role: 'assistant',
          isError: true,
          text: "Sorry, I couldn't reach the support service. Please try again in a moment.",
          sources: [],
        },
      ])
    } finally {
      busy.current = false
      setIsLoading(false)
    }
  }, [])

  const reset = useCallback(() => {
    sessionId.current = null
    writeSessionId(null)
    setMessages([WELCOME])
  }, [])

  return { messages, isLoading, send, reset }
}   