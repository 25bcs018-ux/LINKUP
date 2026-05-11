(() => {
  const canvas = document.getElementById('snakeCanvas');
  const ctx = canvas.getContext('2d');
  const startBtn = document.getElementById('startBtn');
  const overlay = document.getElementById('overlay');
  const arena = document.querySelector('.snake__arena');
  const voidId = document.body?.dataset?.voidId || 'guest';
  const BEST_KEY = `snake_best_${voidId}`;
  const scoreEl = document.getElementById('score');
  const bestEl = document.getElementById('bestScore');
  const speedEl = document.getElementById('speedSelect');
  const speedLabel = document.getElementById('speedLabel');
  const lengthEl = document.getElementById('length');
  const levelEl = document.getElementById('level');
  const applesEl = document.getElementById('apples');
  const levelProgress = document.getElementById('levelProgress');
  const pauseBtn = document.getElementById('pauseBtn');
  const controlButtons = Array.from(document.querySelectorAll('[data-dir]'));

  const GRID = 18;
  const CELL = 20;
  const CANVAS_SIZE = GRID * CELL;
  canvas.width = CANVAS_SIZE;
  canvas.height = CANVAS_SIZE;

  const SPEEDS = {
    slow: 140,
    normal: 110,
    fast: 85
  };

  let state = {
    snake: [{ x: 9, y: 9 }],
    dir: { x: 1, y: 0 },
    nextDir: { x: 1, y: 0 },
    food: { x: 4, y: 4 },
    foodType: 'normal',
    score: 0,
    apples: 0,
    level: 1,
    best: Number(localStorage.getItem(BEST_KEY) || '0'),
    running: false,
    paused: false,
    timer: null
  };

  function setBest(value) {
    state.best = value;
    localStorage.setItem(BEST_KEY, String(value));
  }

  function updateHUD() {
    scoreEl.textContent = String(state.score);
    bestEl.textContent = String(state.best);
    speedLabel.textContent = speedEl.value[0].toUpperCase() + speedEl.value.slice(1);
    lengthEl.textContent = String(state.snake.length);
    levelEl.textContent = String(state.level);
    applesEl.textContent = String(state.apples);
    if (levelProgress) {
      const progress = (state.apples % 5) / 5;
      levelProgress.style.width = `${Math.round(progress * 100)}%`;
    }
  }

  function randomCell() {
    return {
      x: Math.floor(Math.random() * GRID),
      y: Math.floor(Math.random() * GRID)
    };
  }

  function spawnFood() {
    let pos = randomCell();
    while (state.snake.some((seg) => seg.x === pos.x && seg.y === pos.y)) {
      pos = randomCell();
    }
    state.food = pos;
    state.foodType = Math.random() < 0.2 ? 'bonus' : 'normal';
  }

  function resetGame() {
    state.snake = [{ x: 9, y: 9 }];
    state.dir = { x: 1, y: 0 };
    state.nextDir = { x: 1, y: 0 };
    state.score = 0;
    state.apples = 0;
    state.level = 1;
    spawnFood();
    updateHUD();
  }

  function drawGrid() {
    ctx.strokeStyle = 'rgba(108, 246, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= GRID; i += 1) {
      ctx.beginPath();
      ctx.moveTo(i * CELL, 0);
      ctx.lineTo(i * CELL, CANVAS_SIZE);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, i * CELL);
      ctx.lineTo(CANVAS_SIZE, i * CELL);
      ctx.stroke();
    }
  }

  function draw() {
    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    ctx.fillStyle = '#0b0f1a';
    ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    drawGrid();

    ctx.fillStyle = state.foodType === 'bonus' ? '#ffd166' : '#9eff7a';
    ctx.shadowColor = state.foodType === 'bonus' ? 'rgba(255, 209, 102, 0.7)' : 'rgba(158, 255, 122, 0.5)';
    ctx.shadowBlur = 12;
    ctx.fillRect(state.food.x * CELL + 2, state.food.y * CELL + 2, CELL - 4, CELL - 4);
    ctx.shadowBlur = 0;

    state.snake.forEach((seg, idx) => {
      ctx.fillStyle = idx === 0 ? '#6cf6ff' : '#5ab1ff';
      ctx.fillRect(seg.x * CELL + 2, seg.y * CELL + 2, CELL - 4, CELL - 4);
      if (idx === 0) {
        ctx.fillStyle = '#0b0f1a';
        ctx.fillRect(seg.x * CELL + 12, seg.y * CELL + 7, 3, 3);
        ctx.fillRect(seg.x * CELL + 6, seg.y * CELL + 7, 3, 3);
      }
    });
  }

  function tick() {
    state.dir = { ...state.nextDir };
    const head = state.snake[0];
    const next = { x: head.x + state.dir.x, y: head.y + state.dir.y };

    if (next.x < 0 || next.x >= GRID || next.y < 0 || next.y >= GRID) {
      endGame();
      return;
    }

    if (state.snake.some((seg, idx) => idx > 0 && seg.x === next.x && seg.y === next.y)) {
      endGame();
      return;
    }

    state.snake.unshift(next);

    if (next.x === state.food.x && next.y === state.food.y) {
      const gain = state.foodType === 'bonus' ? 3 : 1;
      state.score += gain;
      state.apples += 1;
      if (state.apples % 5 === 0) {
        state.level += 1;
        bumpSpeed();
      }
      if (state.score > state.best) setBest(state.score);
      spawnFood();
    } else {
      state.snake.pop();
    }

    updateHUD();
    draw();
  }

  function startGame() {
    resetGame();
    overlay.style.display = 'none';
    state.running = true;
    state.paused = false;
    pauseBtn.textContent = 'Pause';
    clearInterval(state.timer);
    state.timer = setInterval(tick, getCurrentSpeed());
    draw();
  }

  function endGame() {
    state.running = false;
    state.paused = false;
    clearInterval(state.timer);
    overlay.style.display = 'grid';
    overlay.querySelector('.overlay-title').textContent = 'Game Over';
    overlay.querySelector('.overlay-sub').textContent = 'Tap start to try again.';
    pauseBtn.textContent = 'Pause';
  }

  function getCurrentSpeed() {
    const base = SPEEDS[speedEl.value];
    const bonus = Math.min(40, (state.level - 1) * 4);
    return Math.max(60, base - bonus);
  }

  function bumpSpeed() {
    if (!state.running) return;
    clearInterval(state.timer);
    state.timer = setInterval(tick, getCurrentSpeed());
  }

  function togglePause() {
    if (!state.running) return;
    state.paused = !state.paused;
    if (state.paused) {
      clearInterval(state.timer);
      overlay.style.display = 'grid';
      overlay.querySelector('.overlay-title').textContent = 'Paused';
      overlay.querySelector('.overlay-sub').textContent = 'Tap resume or press space.';
      pauseBtn.textContent = 'Resume';
    } else {
      overlay.style.display = 'none';
      pauseBtn.textContent = 'Pause';
      state.timer = setInterval(tick, getCurrentSpeed());
    }
  }

  function setDir(dir) {
    if (!state.running) return;
    const opposite = state.dir.x + dir.x === 0 && state.dir.y + dir.y === 0;
    if (opposite) return;
    state.nextDir = dir;
  }

  function handleKey(event) {
    if (event.key === ' ') {
      if (!state.running) {
        startGame();
      } else {
        togglePause();
      }
      return;
    }
    if (event.key === 'ArrowUp') setDir({ x: 0, y: -1 });
    if (event.key === 'ArrowDown') setDir({ x: 0, y: 1 });
    if (event.key === 'ArrowLeft') setDir({ x: -1, y: 0 });
    if (event.key === 'ArrowRight') setDir({ x: 1, y: 0 });
  }

  let touchStart = null;
  function handleTouchStart(event) {
    const touch = event.changedTouches[0];
    touchStart = { x: touch.clientX, y: touch.clientY };
  }

  function handleTouchEnd(event) {
    if (!touchStart) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - touchStart.x;
    const dy = touch.clientY - touchStart.y;
    const absX = Math.abs(dx);
    const absY = Math.abs(dy);
    if (Math.max(absX, absY) < 20) return;
    if (absX > absY) {
      setDir({ x: dx > 0 ? 1 : -1, y: 0 });
    } else {
      setDir({ x: 0, y: dy > 0 ? 1 : -1 });
    }
  }

  function handleOverlayTap() {
    if (!state.running) {
      startGame();
      return;
    }
    togglePause();
  }

  startBtn.addEventListener('click', startGame);
  pauseBtn.addEventListener('click', togglePause);
  overlay.addEventListener('click', handleOverlayTap);
  speedEl.addEventListener('change', () => {
    updateHUD();
    if (state.running) {
      clearInterval(state.timer);
      state.timer = setInterval(tick, getCurrentSpeed());
    }
  });

  controlButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const dir = btn.dataset.dir;
      if (dir === 'up') setDir({ x: 0, y: -1 });
      if (dir === 'down') setDir({ x: 0, y: 1 });
      if (dir === 'left') setDir({ x: -1, y: 0 });
      if (dir === 'right') setDir({ x: 1, y: 0 });
    });
  });

  document.addEventListener('keydown', handleKey);
  arena?.addEventListener('touchstart', handleTouchStart, { passive: true });
  arena?.addEventListener('touchend', handleTouchEnd, { passive: true });

  updateHUD();
  draw();
})();
