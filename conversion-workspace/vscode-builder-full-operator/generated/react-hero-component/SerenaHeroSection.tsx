import React from "react";

export default function SerenaHeroSection() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20">
      <p className="mb-3 text-sm font-semibold uppercase tracking-wide">
        Built with Serena
      </p>
      <h1 className="max-w-4xl text-4xl font-bold tracking-tight md:text-6xl">
        Build High Quality Websites With Serena
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8">
        Serena can generate local React components, docs, and build reports while keeping deployment approval-gated.
      </p>
      <div className="mt-8">
        <a
          href="#component-review"
          className="inline-flex min-h-12 items-center rounded-full px-6 font-semibold shadow-sm"
        >
          Review component
        </a>
      </div>
    </section>
  );
}
