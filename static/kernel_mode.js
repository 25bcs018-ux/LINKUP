(() => {
  const kernelBtn = document.getElementById('kernelBtn');
  if (!kernelBtn) return;

  kernelBtn.addEventListener('click', () => {
    window.location.href = '/kernel';
  });
})();
