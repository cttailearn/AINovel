export function reportWebVitals() {
  if (typeof window === 'undefined') return;
  import('web-vitals')
    .then(({ onCLS, onFCP, onINP, onLCP, onTTFB }) => {
      const log = (metric) => {
        // 修复 #40: 先把 Web Vitals 上报到 console，后续可切到后端 collector.
        // eslint-disable-next-line no-console
        console.info('[WebVitals]', metric.name, metric.value, metric);
      };
      onCLS(log);
      onFCP(log);
      onINP(log);
      onLCP(log);
      onTTFB(log);
    })
    .catch(() => {
      // noop
    });
}
