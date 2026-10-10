import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';
import { describe, expect, it } from 'vitest';

function renderMath(markdown: string) {
  return renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
      {markdown}
    </ReactMarkdown>,
  );
}

describe('patched KaTeX with the Markdown plugins', () => {
  it('renders inline and display equations', () => {
    const html = renderMath('Inline $x^2$\n\n$$\n\\frac{1}{2}\n$$');
    expect(html).toContain('class="katex"');
    expect(html).toContain('class="katex-display"');
    expect(html).toContain('<math');
    expect(html).not.toContain('katex-error');
  });

  it('does not enable untrusted HTML commands', () => {
    const html = renderMath('$\\href{javascript:alert(1)}{click}$');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<a ');
  });
});
