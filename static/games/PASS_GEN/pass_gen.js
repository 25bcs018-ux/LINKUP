(() => {
  const difficultyEl = document.getElementById('difficulty');
  const timeLimitEl = document.getElementById('timeLimit');
  const startBtn = document.getElementById('startGame');
  const timerEl = document.getElementById('timer');
  const passLengthEl = document.getElementById('passLength');
  const maskedEl = document.getElementById('maskedPassword');
  const narratorEl = document.getElementById('narrator');
  const guessInput = document.getElementById('guessInput');
  const guessBtn = document.getElementById('guessBtn');
  const cheatBtn = document.getElementById('cheatBtn');
  const giveUpBtn = document.getElementById('giveUpBtn');
  const newRoundBtn = document.getElementById('newRoundBtn');
  const hintList = document.getElementById('hintList');
  const cheatList = document.getElementById('cheatList');
  const attemptsEl = document.getElementById('attemptsLeft');
  const cheatTokensEl = document.getElementById('cheatTokens');
  const defaultHintsEl = document.getElementById('defaultHints');
  const scoreEl = document.getElementById('score');
  const streakEl = document.getElementById('streak');
  const bestEl = document.getElementById('bestScore');

  const DIFFICULTY = {
    easy: {
      length: 4,
      chars: 'ABCDEFGHJKLMNPQRSTUVWXYZ',
      time: 45,
      hints: 3,
      attempts: 6,
      points: 120
    },
    medium: {
      length: 6,
      chars: 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789',
      time: 40,
      hints: 2,
      attempts: 6,
      points: 200
    },
    hard: {
      length: 8,
      chars: 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789!@#$%',
      time: 35,
      hints: 1,
      attempts: 5,
      points: 320
    }
  };

  let state = {
    password: '',
    masked: '',
    hints: [],
    cheats: [],
    hintIndex: 0,
    cheatIndex: 0,
    attemptsLeft: 0,
    defaultHints: 0,
    cheatTokens: 2,
    timer: 0,
    timerId: null,
    score: 0,
    streak: 0,
    active: false
  };

  const voidId = document.body?.dataset?.voidId || 'guest';
  const CHEAT_KEY = `pass_gen_cheats_${voidId}`;
  const BEST_KEY = `pass_gen_best_${voidId}`;
  const MAX_CHEATS = 4;

  function randInt(max) {
    if (window.crypto && window.crypto.getRandomValues) {
      const buffer = new Uint32Array(1);
      window.crypto.getRandomValues(buffer);
      return buffer[0] % max;
    }
    return Math.floor(Math.random() * max);
  }

  function buildPassword(diff) {
    let out = '';
    for (let i = 0; i < diff.length; i += 1) {
      out += diff.chars[randInt(diff.chars.length)];
    }
    return out;
  }

  function buildHints(password) {
    const len = password.length;
    const hints = [
      `Length: ${len}`,
      `Starts with: ${password[0]}`,
      `Ends with: ${password[len - 1]}`,
      `Has numbers: ${/\d/.test(password) ? 'Yes' : 'No'}`,
      `Has symbols: ${/[^A-Z0-9]/.test(password) ? 'Yes' : 'No'}`
    ];
    if (len >= 4) {
      const pos = randInt(len - 2) + 2;
      hints.push(`Character #${pos}: ${password[pos - 1]}`);
    }
    return shuffle(hints);
  }

  function shuffle(items) {
    const out = [...items];
    for (let i = out.length - 1; i > 0; i -= 1) {
      const j = randInt(i + 1);
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  }

  function updateStats() {
    attemptsEl.textContent = String(state.attemptsLeft);
    cheatTokensEl.textContent = String(state.cheatTokens);
    defaultHintsEl.textContent = String(state.defaultHints);
    timerEl.textContent = state.timer > 0 ? `${state.timer}s` : '--';
    if (passLengthEl) passLengthEl.textContent = state.password ? String(state.password.length) : '--';
    scoreEl.textContent = String(state.score);
    streakEl.textContent = String(state.streak);
    bestEl.textContent = String(getBestScore());
  }

  function updateMasked() {
    maskedEl.textContent = state.masked;
  }

  function updateNarrator(message) {
    narratorEl.textContent = message;
  }

  function clearHints() {
    hintList.innerHTML = '';
  }

  function clearCheats() {
    cheatList.innerHTML = '';
  }

  function addHint(text) {
    const li = document.createElement('li');
    li.textContent = text;
    hintList.appendChild(li);
  }

  function addCheat(text) {
    const li = document.createElement('li');
    li.textContent = text;
    cheatList.appendChild(li);
  }

  function getBestScore() {
    return Number(localStorage.getItem(BEST_KEY) || '0');
  }

  function setBestScore(value) {
    localStorage.setItem(BEST_KEY, String(value));
  }

  function getCheatTokens() {
    const stored = Number(localStorage.getItem(CHEAT_KEY));
    if (Number.isNaN(stored) || stored <= 0) return 2;
    return Math.min(stored, MAX_CHEATS);
  }

  function setCheatTokens(value) {
    const next = Math.max(0, Math.min(value, MAX_CHEATS));
    state.cheatTokens = next;
    localStorage.setItem(CHEAT_KEY, String(next));
  }

  function stopTimer() {
    if (state.timerId) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function buildCheats(password) {
    const len = password.length;
    const revealCount = Math.max(2, Math.ceil(len / 2));
    const revealed = password
      .split('')
      .map((char, idx) => (idx < revealCount ? char : '•'))
      .join('');
    return [
      `Cheat 1: Starts with ${revealed}`,
      `Cheat 2: Password is ${password}`
    ];
  }

  function endRound(success, reason) {
    state.active = false;
    stopTimer();
    guessInput.disabled = true;
    guessBtn.disabled = true;
    cheatBtn.disabled = true;
    giveUpBtn.disabled = true;

    if (success) {
      const diff = DIFFICULTY[difficultyEl.value];
      const bonus = Math.max(0, state.timer) * 3;
      const earned = diff.points + bonus;
      state.score += earned;
      state.streak += 1;
      setCheatTokens(state.cheatTokens + 1);
      if (state.score > getBestScore()) {
        setBestScore(state.score);
      }
      updateNarrator(`Correct. +${earned} points. You earned a cheat token.`);
    } else {
      state.streak = 0;
      updateNarrator(`Mission failed. ${reason} Correct answer: ${state.password}`);
      addHint(`Password was: ${state.password}`);
    }

    updateStats();
  }

  function startRound() {
    stopTimer();
    const diff = DIFFICULTY[difficultyEl.value];
    state.password = buildPassword(diff);
    state.hints = buildHints(state.password);
    state.cheats = buildCheats(state.password);
    state.hintIndex = 0;
    state.cheatIndex = 0;
    state.attemptsLeft = diff.attempts;
    state.cheatTokens = getCheatTokens();

    const timeChoice = timeLimitEl.value === 'auto' ? diff.time : Number(timeLimitEl.value);
    const hintChoice = diff.hints;

    state.timer = timeChoice;
    state.defaultHints = Math.min(hintChoice, state.hints.length);
    state.masked = '•'.repeat(diff.length);
    state.active = true;

    clearHints();
    clearCheats();
    for (let i = 0; i < state.defaultHints; i += 1) {
      addHint(state.hints[i]);
    }
    updateMasked();
    updateStats();
    updateNarrator(`Round started. Password length is ${state.password.length}. Default hints are live.`);

    guessInput.disabled = false;
    guessBtn.disabled = false;
    cheatBtn.disabled = false;
    giveUpBtn.disabled = false;
    guessInput.value = '';
    guessInput.maxLength = state.password.length;
    guessInput.placeholder = `Enter ${state.password.length} chars`;
    guessInput.focus();

    state.timerId = setInterval(() => {
      state.timer -= 1;
      updateStats();
      if (state.timer <= 0) {
        endRound(false, 'Time expired.');
      }
    }, 1000);
  }

  function handleGuess() {
    if (!state.active) return;
    const guess = guessInput.value.trim().toUpperCase();
    if (!guess) return;

    if (guess.length !== state.password.length) {
      updateNarrator(`Length mismatch. Enter ${state.password.length} characters.`);
      return;
    }

    if (guess === state.password) {
      endRound(true, 'You cracked it.');
      return;
    }

    state.attemptsLeft -= 1;
    updateNarrator(`No match. You have ${state.attemptsLeft} attempts left.`);
    updateStats();
    guessInput.value = '';

    if (state.attemptsLeft <= 0) {
      endRound(false, 'Attempts exhausted.');
    }
  }

  function handleCheat() {
    if (!state.active) return;
    if (state.cheatTokens <= 0) {
      updateNarrator('No cheat tokens left. Win a round to earn one.');
      return;
    }
    if (state.cheatIndex >= state.cheats.length) {
      updateNarrator('No cheat intel remaining.');
      return;
    }

    const cheat = state.cheats[state.cheatIndex];
    state.cheatIndex += 1;
    setCheatTokens(state.cheatTokens - 1);
    addCheat(cheat);
    updateNarrator('Cheat intel unlocked.');
    updateStats();
  }

  function handleGiveUp() {
    if (!state.active) return;
    endRound(false, 'You walked away.');
  }

  startBtn.addEventListener('click', startRound);
  newRoundBtn.addEventListener('click', startRound);
  guessBtn.addEventListener('click', handleGuess);
  cheatBtn.addEventListener('click', handleCheat);
  giveUpBtn.addEventListener('click', handleGiveUp);
  guessInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') handleGuess();
  });
  guessInput.addEventListener('input', () => {
    if (!state.password) return;
    if (guessInput.value.length > state.password.length) {
      guessInput.value = guessInput.value.slice(0, state.password.length);
    }
  });

  updateStats();
  updateMasked();
  setCheatTokens(getCheatTokens());
  updateStats();
})();
