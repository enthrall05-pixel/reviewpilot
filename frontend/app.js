// ╔══════════════════╗
// ║  Created by G/C  ║
// ╚══════════════════╝

const API = '';  // same origin — FastAPI serves both

// ── Device ID ──────────────────────────────────────────────────────────────
function getDeviceId() {
  let id = localStorage.getItem('rp_device_id');
  if (!id) {
    id = 'rp_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem('rp_device_id', id);
  }
  return id;
}

const DEVICE_ID = getDeviceId();

// ── State ───────────────────────────────────────────────────────────────────
let selectedTone = 'professional';

// ── Init ────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tone-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tone-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedTone = btn.dataset.tone;
    });
  });

  if (location.search.includes('upgraded=1')) {
    document.getElementById('upgrade-success').classList.remove('hidden');
    history.replaceState({}, '', '/');
    localStorage.setItem('rp_tier', 'pro');
  }

  if (localStorage.getItem('rp_tier') === 'pro') {
    showProBadge();
  }

  loadHistory();
});

// ── Generate ─────────────────────────────────────────────────────────────────
async function generate() {
  const review = document.getElementById('review').value.trim();
  if (!review) {
    alert('Paste a review first.');
    return;
  }

  setLoading(true);

  try {
    const res = await fetch(`${API}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: DEVICE_ID,
        review_text: review,
        business_name: document.getElementById('business').value.trim(),
        platform: document.getElementById('platform').value,
        rating: parseInt(document.getElementById('rating').value),
        tone: selectedTone,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      alert(data.error || 'Something went wrong. Try again.');
      return;
    }

    if (data.upgrade) {
      showUpgradeWall();
      return;
    }

    showReplies(data.replies, data.messages_left, data.near_limit, data.tier);
    loadHistory();

  } catch (err) {
    alert('Network error — check your connection.');
    console.error(err);
  } finally {
    setLoading(false);
  }
}

// ── Show Replies ─────────────────────────────────────────────────────────────
const LABELS = ['Short & Punchy', 'Standard', 'Detailed'];

function makeReplyCard(text, index) {
  const card = document.createElement('div');
  card.className = 'reply-card';

  const label = document.createElement('div');
  label.className = 'reply-label';
  label.textContent = `Reply ${index + 1} — ${LABELS[index] || ''}`;

  const body = document.createElement('div');
  body.className = 'reply-text';
  body.textContent = text;  // textContent — safe, no XSS

  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-btn';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => copyReply(copyBtn, text));

  card.appendChild(label);
  card.appendChild(body);
  card.appendChild(copyBtn);
  return card;
}

function showReplies(replies, messagesLeft, nearLimit, tier) {
  const section = document.getElementById('results');
  const container = document.getElementById('replies-container');
  container.innerHTML = '';

  replies.forEach((text, i) => {
    container.appendChild(makeReplyCard(text, i));
  });

  const msg = document.getElementById('near-limit-msg');
  if (nearLimit && tier === 'free' && messagesLeft !== null) {
    msg.textContent = `⚠️ ${messagesLeft} free ${messagesLeft === 1 ? 'reply' : 'replies'} remaining.`;
    msg.classList.remove('hidden');
  } else {
    msg.classList.add('hidden');
  }

  section.classList.remove('hidden');

  if (tier === 'pro') {
    showProBadge();
  } else if (messagesLeft !== null) {
    const badge = document.getElementById('status-badge');
    badge.className = 'badge badge-free';
    const countSpan = document.createElement('span');
    countSpan.id = 'count-left';
    countSpan.textContent = messagesLeft;
    badge.textContent = 'Free — ';
    badge.appendChild(countSpan);
    badge.appendChild(document.createTextNode(' left'));
    badge.classList.remove('hidden');
  }
}

// ── Copy ─────────────────────────────────────────────────────────────────────
function copyReply(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = 'Copy';
      btn.classList.remove('copied');
    }, 2000);
  });
}

// ── Upgrade ──────────────────────────────────────────────────────────────────
function showUpgradeWall() {
  document.getElementById('upgrade-wall').classList.remove('hidden');
}

async function upgrade() {
  try {
    const res = await fetch(`${API}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: DEVICE_ID }),
    });
    const data = await res.json();
    if (data.url) {
      window.location.href = data.url;
    } else {
      alert('Checkout error — try again.');
    }
  } catch (err) {
    alert('Network error — try again.');
  }
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch(`${API}/history?device_id=${encodeURIComponent(DEVICE_ID)}`);
    const data = await res.json();
    const reviews = data.reviews || [];

    const section = document.getElementById('history-section');
    const list = document.getElementById('history-list');

    if (reviews.length === 0) {
      section.classList.add('hidden');
      return;
    }

    list.innerHTML = '';
    reviews.forEach(r => {
      const item = document.createElement('div');
      item.className = 'history-item';

      const meta = document.createElement('div');
      meta.className = 'history-meta';
      const date = new Date(r.created_at).toLocaleDateString();
      meta.textContent = `${r.platform} · ${r.rating ? r.rating + '★' : 'No rating'} · ${date}`;

      const preview = document.createElement('div');
      preview.className = 'history-preview';
      preview.textContent = r.review_text;  // textContent — safe

      item.appendChild(meta);
      item.appendChild(preview);
      item.addEventListener('click', () => {
        document.getElementById('review').value = r.review_text;
        document.getElementById('business').value = r.business_name || '';
        document.getElementById('platform').value = r.platform;
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });

      list.appendChild(item);
    });

    section.classList.remove('hidden');
  } catch (err) {
    // history is not critical — fail silently
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setLoading(on) {
  const btn = document.getElementById('generate-btn');
  const text = document.getElementById('btn-text');
  const spin = document.getElementById('btn-spinner');
  btn.disabled = on;
  text.textContent = on ? 'Generating...' : 'Generate Replies';
  spin.classList.toggle('hidden', !on);
}

function showProBadge() {
  const badge = document.getElementById('status-badge');
  badge.className = 'badge badge-pro';
  badge.textContent = 'Pro';
  badge.classList.remove('hidden');
  localStorage.setItem('rp_tier', 'pro');
}
