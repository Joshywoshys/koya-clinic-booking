const slotList = document.getElementById("slot-list");
const slotStatus = document.getElementById("slot-status");
const bookingSection = document.getElementById("booking-section");
const selectedSlotText = document.getElementById("selected-slot");
const bookingForm = document.getElementById("booking-form");
const confirmBtn = document.getElementById("confirm-btn");
const formError = document.getElementById("form-error");
const confirmation = document.getElementById("confirmation");
const mineForm = document.getElementById("mine-form");
const mineEmail = document.getElementById("mine-email");
const myList = document.getElementById("my-list");
const moreBtn = document.getElementById("more-btn");
const mineError = document.getElementById("mine-error");
const reschedulePanel = document.getElementById("reschedule-panel");
const rescheduleText = document.getElementById("reschedule-text");
const rescheduleSlots = document.getElementById("reschedule-slots");
const rescheduleError = document.getElementById("reschedule-error");
const rescheduleCancel = document.getElementById("reschedule-cancel");

let selectedSlot = null;
let idempotencyKey = null;
let mineCursor = null;
let rescheduling = null; // the booking being moved, or null
let busy = false;        // blocks double clicks from sending two requests
let slotIndex = {};      // slot id -> slot, so My bookings can show readable times


function formatTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}


function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}


// ---------- Requests to the server ----------

async function postBooking(payload, key) {
  const res = await fetch("/page/bookings", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    const err = new Error(data.error || "Booking failed");
    err.status = res.status;
    throw err;
  }
  return data;
}


async function cancelRequest(bookingId) {
  const res = await fetch(`/page/bookings/${encodeURIComponent(bookingId)}`, {
    method: "DELETE",
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not cancel the booking");
  return data;
}


// ---------- Slots ----------

async function loadSlots() {
  slotStatus.textContent = "Loading...";
  try {
    const res = await fetch("/page/slots");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load slots");

    slotIndex = Object.fromEntries(data.slots.map((s) => [s.id, s]));

    slotList.innerHTML = "";
    if (data.slots.length === 0) {
      slotStatus.textContent = "No appointments are available right now.";
      return;
    }
    slotStatus.textContent = "";

    for (const slot of data.slots) {
      const li = document.createElement("li");

      const info = document.createElement("div");
      info.className = "slot-info";
      info.innerHTML = `<strong>${escapeHtml(slot.provider)}</strong>
        <span>${formatTime(slot.start)} – ${formatTime(slot.end)}</span>`;

      const action = document.createElement("div");
      const badge = document.createElement("span");
      if (slot.available) {
        badge.className = "badge";
        badge.textContent = "Available";
        const btn = document.createElement("button");
        btn.className = "small";
        btn.textContent = "Book appointment";
        btn.onclick = () => selectSlot(slot);
        action.append(badge, " ", btn);
      } else {
        badge.className = "badge booked";
        badge.textContent = "Booked";
        action.append(badge);
      }

      li.append(info, action);
      slotList.append(li);
    }
  } catch (err) {
    slotStatus.textContent = err.message;
  }
}


// ---------- Booking ----------

function selectSlot(slot) {
  selectedSlot = slot;
  idempotencyKey = null;
  selectedSlotText.textContent = `Booking: ${slot.provider}, ${formatTime(slot.start)}`;
  formError.textContent = "";
  bookingSection.hidden = false;
  confirmation.hidden = true;
  bookingSection.scrollIntoView({ behavior: "smooth" });
}


bookingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedSlot || busy) return;

  busy = true;
  formError.textContent = "";
  confirmBtn.disabled = true;
  idempotencyKey = idempotencyKey || crypto.randomUUID();

  try {
    const booking = await postBooking(
      {
        slot_id: selectedSlot.id,
        name: document.getElementById("name").value,
        email: document.getElementById("email").value,
      },
      idempotencyKey
    );
    showConfirmation(booking, selectedSlot);
    bookingForm.reset();
    bookingSection.hidden = true;
    selectedSlot = null;
    idempotencyKey = null;
    loadSlots();
  } catch (err) {
    formError.textContent = err.message;
    // A server answer ends this attempt, so the next submit gets a fresh key
    if (err.status) idempotencyKey = null;
  } finally {
    confirmBtn.disabled = false;
    busy = false;
  }
});


function showConfirmation(booking, slot) {
  confirmation.innerHTML = `
    <h2>Booking confirmed</h2>
    <dl>
      <dt>Reference</dt><dd>${escapeHtml(booking.id)}</dd>
      <dt>Patient</dt><dd>${escapeHtml(booking.name)}</dd>
      <dt>Email</dt><dd>${escapeHtml(booking.email)}</dd>
      <dt>Provider</dt><dd>${escapeHtml(slot.provider)}</dd>
      <dt>When</dt><dd>${formatTime(slot.start)}</dd>
    </dl>
    <p id="cancel-msg" class="error"></p>
    <button id="cancel-btn" class="small" type="button">Cancel this booking</button>`;
  confirmation.hidden = false;

  document.getElementById("cancel-btn").onclick = async () => {
    const btn = document.getElementById("cancel-btn");
    const msg = document.getElementById("cancel-msg");
    btn.disabled = true;
    try {
      await cancelRequest(booking.id);
      confirmation.innerHTML = `
        <h2>Booking cancelled</h2>
        <p>Reference: ${escapeHtml(booking.id)}</p>`;
      loadSlots();
    } catch (err) {
      msg.textContent = err.message;
      btn.disabled = false;
    }
  };
}


// ---------- My bookings ----------

async function refreshSlotIndex() {
  const res = await fetch("/page/slots");
  const data = await res.json();
  if (res.ok) slotIndex = Object.fromEntries(data.slots.map((s) => [s.id, s]));
}


function describeSlot(slotId) {
  const s = slotIndex[slotId];
  return s ? `${s.provider}, ${formatTime(s.start)}` : slotId;
}


async function loadMine(reset) {
  mineError.textContent = "";
  const email = mineEmail.value.trim();
  if (!email) {
    mineError.textContent = "Enter your email address.";
    return;
  }
  if (reset) {
    myList.innerHTML = "";
    mineCursor = null;
  }

  const params = new URLSearchParams({ email, limit: "5" });
  if (mineCursor) params.set("cursor", mineCursor);

  try {
    await refreshSlotIndex();
    const res = await fetch(`/page/bookings?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load bookings");

    if (reset && data.bookings.length === 0) {
      myList.textContent = "No bookings found for this email.";
    }
    for (const b of data.bookings) {
      myList.append(bookingItem(b));
    }
    mineCursor = data.next_cursor;
    moreBtn.hidden = !mineCursor;
  } catch (err) {
    mineError.textContent = err.message;
  }
}


function bookingItem(b) {
  const li = document.createElement("li");

  const info = document.createElement("div");
  info.className = "slot-info";
  info.innerHTML = `<strong>${escapeHtml(describeSlot(b.slot_id))}</strong>
    <span>${escapeHtml(b.name)} · ${escapeHtml(b.status)} · Reference: ${escapeHtml(b.id)}</span>`;
  li.append(info);

  if (b.status === "confirmed") {
    const actions = document.createElement("div");

    const resBtn = document.createElement("button");
    resBtn.className = "small";
    resBtn.textContent = "Reschedule";
    resBtn.onclick = () => startReschedule(b);

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "small";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = async () => {
      cancelBtn.disabled = true;
      try {
        await cancelRequest(b.id);
        if (rescheduling && rescheduling.id === b.id) stopReschedule();
        loadSlots();
        loadMine(true);
      } catch (err) {
        mineError.textContent = err.message;
        cancelBtn.disabled = false;
      }
    };

    actions.append(resBtn, " ", cancelBtn);
    li.append(actions);
  }
  return li;
}


mineForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadMine(true);
});

moreBtn.addEventListener("click", () => loadMine(false));


// ---------- Reschedule ----------

function startReschedule(b) {
  rescheduling = b;
  rescheduleText.textContent =
    `Choose a new time for ${describeSlot(b.slot_id)} (reference ${b.id}). ` +
    "Your current booking is kept until the new one is confirmed.";
  reschedulePanel.hidden = false;
  loadRescheduleSlots();
  reschedulePanel.scrollIntoView({ behavior: "smooth" });
}


function stopReschedule() {
  rescheduling = null;
  reschedulePanel.hidden = true;
  rescheduleSlots.innerHTML = "";
  rescheduleError.textContent = "";
}


rescheduleCancel.addEventListener("click", stopReschedule);


async function loadRescheduleSlots() {
  rescheduleSlots.innerHTML = "";
  rescheduleError.textContent = "";
  try {
    const res = await fetch("/page/slots");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load slots");

    const free = data.slots.filter((s) => s.available);
    if (free.length === 0) {
      rescheduleSlots.textContent = "No free slots right now.";
      return;
    }

    for (const slot of free) {
      const li = document.createElement("li");

      const info = document.createElement("div");
      info.className = "slot-info";
      info.innerHTML = `<strong>${escapeHtml(slot.provider)}</strong>
        <span>${formatTime(slot.start)} – ${formatTime(slot.end)}</span>`;

      const btn = document.createElement("button");
      btn.className = "small";
      btn.textContent = "Move here";
      btn.onclick = () => moveTo(slot);

      li.append(info, btn);
      rescheduleSlots.append(li);
    }
  } catch (err) {
    rescheduleError.textContent = err.message;
  }
}


async function moveTo(slot) {
  if (!rescheduling || busy) return;
  busy = true;
  const old = rescheduling;
  rescheduleError.textContent = "";
  rescheduleSlots.querySelectorAll("button").forEach((b) => (b.disabled = true));

  try {
    // Step 1: book the new slot. If this fails (for example, someone else took it),
    // the old booking is untouched.
    const newBooking = await postBooking(
      { slot_id: slot.id, name: old.name, email: old.email },
      crypto.randomUUID()
    );

    // Step 2: cancel the old booking
    try {
      await cancelRequest(old.id);
    } catch (err) {
      stopReschedule();
      confirmation.innerHTML = `
        <h2>Partly rescheduled</h2>
        <p>Your new booking is <strong>${escapeHtml(newBooking.id)}</strong>, but the old
        booking ${escapeHtml(old.id)} could not be cancelled. Please contact the clinic
        to cancel it.</p>`;
      confirmation.hidden = false;
      loadSlots();
      loadMine(true);
      return;
    }

    stopReschedule();
    showConfirmation(newBooking, slot);
    loadSlots();
    loadMine(true);
  } catch (err) {
    rescheduleError.textContent = err.message;
    rescheduleSlots.querySelectorAll("button").forEach((b) => (b.disabled = false));
  } finally {
    busy = false;
  }
}


loadSlots();