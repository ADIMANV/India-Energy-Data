"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";

// Repo-relative links (../scrapers/..., emission_factors.json) don't resolve on
// the web host — render those as plain text. Keep http(s) links clickable and
// open external ones in a new tab.
function Anchor({ href = "", children, ...props }) {
  const external = /^https?:\/\//.test(href);
  if (!external && !href.startsWith("#")) {
    return <span>{children}</span>;
  }
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
      {...props}
    >
      {children}
    </a>
  );
}

export default function MarkdownDoc({ markdown }) {
  return (
    <article className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug]}
        components={{ a: Anchor }}
      >
        {markdown}
      </ReactMarkdown>
    </article>
  );
}
