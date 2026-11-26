import { useState } from 'react'
import ChatWidget from './ChatWidget.jsx'
import './storefront.css'

const PRODUCTS = [
  { name: 'AeroRun', tag: 'Road running', price: 129, color: '#d9480f', bg: '#ffe8d9', image: '/shoes/aerorun.jpg' },
  { name: 'TrailBlazer GTX', tag: 'Trail, waterproof', price: 159, color: '#4d6b3c', bg: '#e6efdc', image: '/shoes/trailblazer.jpg' },
  { name: 'CloudStep', tag: 'Everyday comfort', price: 99, color: '#2563eb', bg: '#dbe8ff', image: '/shoes/cloudstep.jpg' },
  { name: 'Midnight Court', tag: 'Basketball', price: 139, color: '#111827', bg: '#e5e7eb', image: '/shoes/midnight-court.jpg' },
]

const PERKS = ['30-day easy returns', 'Free shipping over $75', '2-year warranty', 'Size guide for every pair']

const HELP_TOPICS = [
  { title: 'Returns & refunds', text: '30 days from delivery, unworn, in the original box. Refunds take 5-7 business days.', ask: 'How do returns work?' },
  { title: 'Order status', text: 'Get live tracking and delivery estimates for any order in seconds.', ask: 'Where is my order?' },
  { title: 'Sizing help', text: 'Not sure which size to pick? We will compare fits across models.', ask: 'Which size should I order in AeroRun?' },
  { title: 'Warranty', text: 'What is covered, what is not, and how to start a claim.', ask: 'What does the warranty cover?' },
]

const QUICK_QUESTIONS = ['Can I return sale shoes?', 'How long does a refund take?', 'Where is my order?']

// Talks to ChatWidget through a window event, so the two components stay independent.
function openChat(question) {
  window.dispatchEvent(new CustomEvent('dk:open-chat', { detail: { question } }))
}

function Shoe({ color }) {
  return (
    <svg className="st-shoe" viewBox="0 0 200 100" aria-hidden="true">
      <path
        d="M10 70 C10 55 30 50 45 48 L70 25 C78 18 90 20 95 28 L105 42 C125 44 160 48 182 60 C192 65 192 78 182 80 L20 80 C13 80 10 76 10 70 Z"
        fill={color}
      />
      <path d="M72 30 L84 44 M82 26 L94 40 M92 32 L102 44" stroke="#fff" strokeWidth="3" strokeLinecap="round" opacity="0.85" />
      <path d="M45 48 C60 56 90 58 105 42" stroke="#fff" strokeWidth="2" fill="none" opacity="0.4" />
      <rect x="6" y="76" width="190" height="13" rx="6.5" fill="#fff" stroke="#111827" strokeWidth="2" />
    </svg>
  )
}

// Shows the real photo; if the file is missing, falls back to the SVG shoe.
function ProductArt({ product }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <div className="st-card-art st-card-art--svg" style={{ background: product.bg }}>
        <Shoe color={product.color} />
      </div>
    )
  }
  return (
    <div className="st-card-art" style={{ background: product.bg }}>
      <img
        className="st-photo"
        src={product.image}
        alt={`${product.name} sneaker`}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </div>
  )
}

export default function App() {
  return (
    <div className="st-page">
      <div className="st-announce">
        Questions about sizing, returns or your order?{' '}
        <button type="button" onClick={() => openChat()}>Ask our assistant</button>
      </div>

      <header className="st-nav">
        <a className="st-logo" href="#top">
          Demo<span>Kicks</span>
        </a>
        <nav aria-label="Main">
          <a href="#shop">Shop</a>
          <a href="#perks">Returns</a>
          <a className="st-nav-support" href="#support">Support</a>
        </nav>
        <button type="button" className="st-cart">Cart (0)</button>
      </header>

      <main id="top">
        <section className="st-hero">
          <div className="st-hero-text">
            <span className="st-badge">New season drop</span>
            <h1>
              Run further.
              <br />
              Look <em>better</em> doing it.
            </h1>
            <p>Performance sneakers for the road, the trail and everything in between.</p>
            <div className="st-cta">
              <a className="st-btn st-btn--primary" href="#shop">Shop now</a>
              <a className="st-btn" href="#support">Get help</a>
            </div>
          </div>
          <div className="st-hero-art" aria-hidden="true">
            <div className="st-blob" />
            <Shoe color="#d9480f" />
          </div>
        </section>

        <section className="st-perks" id="perks">
          {PERKS.map((perk) => (
            <span key={perk}>{perk}</span>
          ))}
        </section>

        <section className="st-shop" id="shop">
          <div className="st-section-head">
            <h2>Best sellers</h2>
            <p>Four pairs people keep coming back for.</p>
          </div>
          <div className="st-grid">
            {PRODUCTS.map((product) => (
              <article className="st-card" key={product.name}>
                <ProductArt product={product} />
                <div className="st-card-body">
                  <div>
                    <h3>{product.name}</h3>
                    <small>{product.tag}</small>
                  </div>
                  <strong>${product.price}</strong>
                </div>
                <button type="button" className="st-add">Add to cart</button>
              </article>
            ))}
          </div>
        </section>

        <section className="st-support" id="support" aria-labelledby="support-title">
          <div className="st-support-inner">
            <div className="st-support-intro">
              <span className="st-badge st-badge--dark">Support</span>
              <h2 id="support-title">We have got your back.</h2>
              <p>
                Instant answers from our AI assistant, grounded in our real policies, with a human
                one click away whenever you want one.
              </p>
              <button type="button" className="st-btn st-btn--accent" onClick={() => openChat()}>
                Chat with our assistant
              </button>

              <div className="st-chips" aria-label="Popular questions">
                {QUICK_QUESTIONS.map((question) => (
                  <button key={question} type="button" onClick={() => openChat(question)}>
                    {question}
                  </button>
                ))}
              </div>

              <dl className="st-contact">
                <div>
                  <dt>Email</dt>
                  <dd>support@demokicks.example</dd>
                </div>
                <div>
                  <dt>Live chat hours</dt>
                  <dd>Mon to Fri, 9 AM to 6 PM EST</dd>
                </div>
              </dl>
            </div>

            <div className="st-topics">
              {HELP_TOPICS.map((topic, index) => (
                <button
                  key={topic.title}
                  type="button"
                  className="st-topic"
                  onClick={() => openChat(topic.ask)}
                >
                  <span className="st-topic-num">0{index + 1}</span>
                  <h3>{topic.title}</h3>
                  <p>{topic.text}</p>
                  <span className="st-topic-link">Ask about this</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="st-footer" id="footer">
        <div>
          <strong>DemoKicks</strong>
          <p>Demo storefront for an AI customer support assistant.</p>
        </div>
        <p>support@demokicks.example · Mon to Fri, 9 AM to 6 PM EST</p>
      </footer>

      <ChatWidget />
    </div>
  )
}