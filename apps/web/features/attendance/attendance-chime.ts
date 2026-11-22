export function prepareAttendanceChime(checkingIn: boolean) {
  let context: AudioContext;
  try {
    context = new AudioContext();
  } catch {
    return;
  }

  // Resume during the button gesture so playback can follow the API response.
  const ready = context.resume().then(() => true, () => false);
  const close = () => { void context.close().catch(() => {}); };
  return (confirmed: boolean) => {
    if (!confirmed) {
      close();
      return;
    }
    void ready.then((resumed) => {
      if (!resumed) {
        close();
        return;
      }
      const notes = checkingIn ? [523.25, 659.25] : [659.25, 523.25];
      const start = context.currentTime;
      notes.forEach((frequency, index) => {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const onset = start + index * 0.13;
        oscillator.frequency.value = frequency;
        gain.gain.setValueAtTime(0, onset);
        gain.gain.linearRampToValueAtTime(0.07, onset + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.001, onset + 0.19);
        oscillator.connect(gain).connect(context.destination);
        if (index === notes.length - 1) oscillator.onended = close;
        oscillator.start(onset);
        oscillator.stop(onset + 0.2);
      });
    }).catch(close);
  };
}
