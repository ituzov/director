"use client";

import { useRef } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import gsap from "gsap";
import { SplitText } from "gsap/SplitText";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP, SplitText);

type DemoComment = { author: string; text: string; match: boolean };

export function Cover() {
  const t = useTranslations("Cover");
  const comments = t.raw("comments") as DemoComment[];

  const root = useRef<HTMLElement>(null);
  const inbox = useRef<HTMLDivElement>(null);
  const counter = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: reduce)", () => {
        gsap.set(".cover-intro", { autoAlpha: 1 });
      });

      mm.add("(prefers-reduced-motion: no-preference)", (ctx) => {
        const bubbles = gsap.utils.toArray<HTMLElement>(".cover-bubble");
        let delivered = 0;
        let next = 0;

        gsap.set(".cover-intro", { autoAlpha: 1 });

        const intro = gsap.timeline({ defaults: { ease: "expo.out" } });
        intro.from(inbox.current, {
          autoAlpha: 0,
          scale: 0.6,
          duration: 0.9,
          ease: "back.out(2)",
        });

        SplitText.create(".cover-title", {
          type: "chars",
          mask: "chars",
          autoSplit: true,
          onSplit: (split) =>
            intro.from(
              split.chars,
              { yPercent: 110, duration: 1.1, stagger: 0.05 },
              0.15,
            ),
        });

        intro.from(
          ".cover-fade",
          { autoAlpha: 0, y: 16, duration: 0.9, stagger: 0.12 },
          0.7,
        );

        // Новые твины создаются уже после старта, поэтому функция
        // регистрируется в контексте: при размонтировании они откатятся.
        // Именованный add возвращает функцию, безымянный выполнил бы её сразу.
        const spawn = ctx.add("spawn", () => {
          const scene = root.current;
          const target = inbox.current;
          if (!scene || !target) return;

          // Берём следующий по кругу пузырь, который сейчас не анимируется.
          let el: HTMLElement | undefined;
          for (let i = 0; i < bubbles.length; i++) {
            const candidate = bubbles[(next + i) % bubbles.length];
            if (!gsap.isTweening(candidate)) {
              el = candidate;
              next = (next + i + 1) % bubbles.length;
              break;
            }
          }
          if (!el) return;

          const sceneBox = scene.getBoundingClientRect();
          const w = el.offsetWidth;
          const h = el.offsetHeight;
          const inTopBand = Math.random() < 0.5;
          const x = gsap.utils.random(16, Math.max(16, sceneBox.width - w - 16));
          const y = inTopBand
            ? gsap.utils.random(sceneBox.height * 0.05, sceneBox.height * 0.24)
            : gsap.utils.random(
                sceneBox.height * 0.74,
                sceneBox.height * 0.92 - h,
              );

          el.dataset.match = "off";
          gsap.set(el, { x, y, autoAlpha: 0, scale: 0.85, rotate: 0 });

          const tl = gsap.timeline();
          tl.to(el, {
            autoAlpha: 1,
            scale: 1,
            duration: 0.5,
            ease: "back.out(2)",
          }).to(el, { y: y - 14, duration: 1.6, ease: "sine.inOut" }, "<");

          if (el.dataset.demoMatch !== "true") {
            tl.to(el, { autoAlpha: 0, y: y - 24, duration: 0.6 });
            return;
          }

          tl.call(() => {
            el.dataset.match = "on";
          }, [], "-=0.6");

          tl.add(() => {
            const inboxBox = target.getBoundingClientRect();
            const tx = inboxBox.left - sceneBox.left + inboxBox.width / 2 - w / 2;
            const ty = inboxBox.top - sceneBox.top + inboxBox.height / 2 - h / 2;

            // Разные изинги по осям дают полёт по дуге без MotionPath.
            gsap
              .timeline({
                onComplete: () => {
                  delivered += 1;
                  if (counter.current) {
                    counter.current.textContent = String(delivered);
                  }
                  gsap.fromTo(
                    target,
                    { scale: 1.12 },
                    { scale: 1, duration: 0.6, ease: "elastic.out(1, 0.4)" },
                  );
                  gsap.fromTo(
                    counter.current,
                    { scale: 1.6 },
                    { scale: 1, duration: 0.5, ease: "back.out(3)" },
                  );
                },
              })
              .to(el, { x: tx, duration: 0.9, ease: "power1.inOut" }, 0)
              .to(el, { y: ty, duration: 0.9, ease: "back.in(1.4)" }, 0)
              .to(el, { scale: 0.2, rotate: -8, duration: 0.9, ease: "power2.in" }, 0)
              .to(el, { autoAlpha: 0, duration: 0.25 }, 0.65);
          }, "+=0.15");
        });

        gsap
          .timeline({ repeat: -1, delay: 1.4 })
          .call(() => spawn())
          .to({}, { duration: 0.85 });
      });
    },
    { scope: root },
  );

  return (
    <main
      ref={root}
      className="relative flex min-h-dvh flex-1 flex-col items-center justify-center overflow-hidden px-4"
    >
      <div aria-hidden className="pointer-events-none absolute inset-0">
        {comments.map((comment) => (
          <div
            key={comment.author}
            data-demo-match={comment.match}
            data-match="off"
            className="cover-bubble invisible absolute left-0 top-0 flex items-center gap-2 rounded-2xl border border-line bg-surface py-2 pl-2 pr-3 transition-colors duration-300 data-[match=on]:border-accent"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-background">
              {comment.author[0].toUpperCase()}
            </span>
            <span className="flex flex-col leading-tight">
              <span className="text-xs font-semibold">{comment.author}</span>
              <span className="whitespace-nowrap text-sm">{comment.text}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="relative z-10 flex max-w-xl flex-col items-center text-center">
        <div
          ref={inbox}
          className="cover-intro invisible relative mb-8 flex size-16 items-center justify-center rounded-xl bg-accent text-background"
          role="img"
          aria-label={t("inbox")}
        >
          <svg
            viewBox="0 0 24 24"
            className="size-8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M21.5 2.5 10.6 13.4" />
            <path d="m21.5 2.5-6.9 19-4-8.1-8.1-4z" />
          </svg>
          <span
            ref={counter}
            className="absolute -right-2 -top-2 flex h-6 min-w-6 items-center justify-center rounded-full border-2 border-background bg-foreground px-1.5 text-xs font-semibold text-background"
          >
            0
          </span>
        </div>

        <h1 className="cover-title cover-intro invisible font-display text-hero md:text-display">
          {t.rich("title", {
            hl: (chunks) => <span className="text-accent">{chunks}</span>,
          })}
        </h1>
        <p className="cover-fade cover-intro invisible mt-5 max-w-md text-base text-muted md:text-lg">
          {t("tagline")}
        </p>
        <Link
          href="/login"
          className="cover-fade cover-intro invisible mt-8 rounded-full bg-foreground px-7 py-3 text-sm font-medium text-background transition-transform hover:scale-[1.03] active:scale-[0.98]"
        >
          {t("cta")}
        </Link>
        <p className="cover-fade cover-intro invisible mt-6 font-mono text-xs text-muted">
          {t("opensource")}
        </p>
      </div>
    </main>
  );
}
