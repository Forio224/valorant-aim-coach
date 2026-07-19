import { useEffect, useRef, useState } from 'react';

/**
 * Каскадный вход по скроллу: вешает наблюдатель на элемент и один раз
 * отдаёт inView=true, когда тот показался. CSS-класс `rv in` доигрывает
 * остальное; при prefers-reduced-motion CSS показывает всё сразу.
 */
function useReveal(threshold = 0.15) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return undefined;
    }
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true);
        io.disconnect();
      }
    }, { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);

  return [ref, inView];
}

export default useReveal;
