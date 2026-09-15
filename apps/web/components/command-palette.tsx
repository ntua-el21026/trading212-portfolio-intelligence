"use client";

import { Search, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { accountHref } from "../lib/account-selection";
import { useAccountSelection } from "./account-context";
import { commandRoutes } from "./navigation";
import Link from "./navigation-intent";
import styles from "./command-palette.module.css";

export function CommandPalette() {
  const { selection } = useAccountSelection();
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const options = commandRoutes.filter((route) =>
    route.label
      .toLocaleLowerCase("en")
      .includes(query.trim().toLocaleLowerCase("en")),
  );
  const open = useCallback(() => {
    if (!dialog.current || dialog.current.open) return;
    setQuery("");
    setActive(0);
    dialog.current.showModal();
    input.current?.focus();
  }, []);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        event.key.toLowerCase() === "k" &&
        !event.repeat
      ) {
        event.preventDefault();
        if (dialog.current?.open) dialog.current.close();
        else open();
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
    };
  }, [open]);
  useEffect(() => {
    dialog.current?.close();
  }, [selection.account?.id]);
  useEffect(() => {
    if (dialog.current?.open)
      list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active, query]);
  return (
    <>
      <button
        className={styles.trigger}
        ref={trigger}
        type="button"
        aria-label="Open command palette"
        aria-haspopup="dialog"
        onClick={open}
      >
        <Search aria-hidden="true" size={19} />
      </button>
      <dialog
        className={styles.dialog}
        ref={dialog}
        aria-labelledby={`${id}-title`}
        onClose={() => trigger.current?.focus()}
      >
        <div className={styles.heading}>
          <h2 id={`${id}-title`}>Go to a workspace</h2>
          <button
            type="button"
            aria-label="Close command palette"
            onClick={() => dialog.current?.close()}
          >
            <X aria-hidden="true" size={20} />
          </button>
        </div>
        <label htmlFor={`${id}-query`}>Search pages</label>
        <input
          ref={input}
          id={`${id}-query`}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          aria-controls={`${id}-options`}
          aria-activedescendant={
            options.length ? `${id}-option-${active}` : undefined
          }
          autoComplete="off"
          maxLength={120}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              if (options.length)
                setActive(
                  (index) =>
                    (index +
                      (event.key === "ArrowDown" ? 1 : options.length - 1)) %
                    options.length,
                );
            } else if (event.key === "Enter" && options.length) {
              event.preventDefault();
              list.current?.children[active]
                ?.querySelector<HTMLAnchorElement>("a")
                ?.click();
            }
          }}
        />
        <ul
          id={`${id}-options`}
          role="listbox"
          aria-label="Workspaces"
          ref={list}
          className={styles.options}
        >
          {options.map((route, index) => (
            <li key={route.href} role="presentation">
              <Link
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                tabIndex={-1}
                prefetch={false}
                href={accountHref(route.href, selection.account?.id ?? null)}
                onClick={() => dialog.current?.close()}
              >
                {route.label}
              </Link>
            </li>
          ))}
        </ul>
        {!options.length ? <p role="status">No matching workspace.</p> : null}
        <p className={styles.help}>
          Ctrl or Command + K to open. Arrow keys to select, Enter to go, Escape
          to close.
        </p>
      </dialog>
    </>
  );
}
