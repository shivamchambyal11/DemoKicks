import { useEffect, useRef, useState } from 'react'
import { IS_MOCK } from './api'
import { useChat } from './useChat'

const QUICK_REPLIES = [
  'Can I return sale shoes?',
  'Where is my order?',
  'How long does a refund take?',
  'Which size should I order in AeroRun?',
]
const MAX_CHARS = 500 // keep in sync with GUARD_MAX_QUESTION_CHARS on the server
const SUPPORT_EMAIL = 'support@demokicks.example'

const ICONS = {
  chat: (
    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
  ),
  close: (
    <>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </>
  ),
  reset: (
    <>
      <polyline points="1 4 1 10 7 10" />
      <polyline points="23 20 23 14 17 14" />
      <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
    </>
  ),
  send: (
    <>
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </>
  ),
}

function Icon({ name }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  )
}

function Message({ message }) {
  const isUser = message.role === 'user'
  const bubbleClass = [
    'dk-bubble',
    isUser ? 'dk-bubble--user' : 'dk-bubble--bot',
    message.isError ? 'dk-bubble--error' : '',
  ].join(' ')

  return (
    <div className={`dk-row ${isUser ? 'dk-row--user' : ''}`}>
      <div className={bubbleClass}>
        {/* Plain text only: React escapes it, so model output can never inject HTML. */}
        <div className="dk-text">{message.text}</div>

        {message.sources?.length > 0 && (
          <div className="dk-sources">
            <span className="dk-sources-label">Sources</span>
            {message.sources.map((source) => (
              <span className="dk-chip" key={source}>
                {source}
              </span>
            ))}
          </div>
        )}

        {message.needsHuman && (
          <a className="dk-human" href={`mailto:${SUPPORT_EMAIL}`}>
            Talk to a human
          </a>
        )}
      </div>
    </div>
  )
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const { messages, isLoading, send, reset } = useChat()
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isLoading, open])

  const submit = (event) => {
    event.preventDefault()
    if (!draft.trim() || isLoading) return
    send(draft)
    setDraft('')
  }

  const showQuickReplies = messages.length === 1 // only the welcome message so far

  return (
    <div className={`dk-widget ${open ? 'dk-widget--open' : ''}`}>
      {open && (
        <section
          className="dk-panel"
          role="dialog"
          aria-label="DemoKicks support chat"
          onKeyDown={(event) => event.key === 'Escape' && setOpen(false)}
        >
          <header className="dk-header">
            <div>
              <strong>DemoKicks Support</strong>
              <small>{IS_MOCK ? 'Demo mode: mock replies' : 'AI assistant, replies in seconds'}</small>
            </div>
            <div className="dk-actions">
              <button type="button" onClick={reset} disabled={isLoading} aria-label="Start a new chat" title="New chat">
                <Icon name="reset" />
              </button>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close chat" title="Close">
                <Icon name="close" />
              </button>
            </div>
          </header>

          <div className="dk-messages" role="log" aria-live="polite">
            {messages.map((message) => (
              <Message key={message.id} message={message} />
            ))}

            {showQuickReplies && (
              <div className="dk-quick">
                {QUICK_REPLIES.map((question) => (
                  <button key={question} type="button" className="dk-quick-btn" onClick={() => send(question)}>
                    {question}
                  </button>
                ))}
              </div>
            )}

            {isLoading && (
              <div className="dk-row" aria-label="Assistant is typing">
                <div className="dk-bubble dk-bubble--bot dk-typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form className="dk-input" onSubmit={submit}>
            <input
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={MAX_CHARS}
              placeholder="Ask about returns, shipping, sizing..."
              aria-label="Your message"
            />
            <button type="submit" disabled={!draft.trim() || isLoading} aria-label="Send message">
              <Icon name="send" />
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        className="dk-launcher"
        onClick={() => setOpen((value) => !value)}
        aria-label={open ? 'Close chat' : 'Open chat'}
        aria-expanded={open}
      >
        <Icon name={open ? 'close' : 'chat'} />
      </button>
    </div>
  )
}