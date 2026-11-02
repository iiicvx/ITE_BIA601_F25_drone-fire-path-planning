// دمج القراءات المتزامنة للملخص المحفوظ نفسه. وتُحذف الوعود المستقرة
// فورًا: فإجراء المستخدم اللاحق يقرأ بيانات الخادم الحالية.
const pending = new Map();
export const isStaticSummary = url => /^\/api\/(?:fleet\/(?:small|medium|large)|table\/(?:main|random|wilcoxon|checks|runs|sensitivity)|cities|special-cases)$/.test(url);
export function readStaticSummary(url) {
  if (pending.has(url)) return pending.get(url);
  const result = fetch(url).then(response => {
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return response.json();
  });
  pending.set(url, result);
  result.then(() => pending.delete(url), () => pending.delete(url));
  return result;
}
