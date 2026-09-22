"use client";
import {
  useEffect,
  useRef,
  useState,
  useTransition,
  type FormEvent,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button, Notice } from "@trading212/ui";
import {
  OwnerLayoutContentSchema,
  type Account,
  type OwnerLayoutContent,
  type OwnerLayoutWidget,
} from "@trading212/api-contracts";
import { submitOwnerLayoutCommand } from "../lib/owner-layout-actions";
import { ownerLayoutHref } from "../lib/owner-layout-query";
import {
  OwnerLayoutSelectionFields,
  initialLayoutSelection,
} from "./owner-layout-selection-fields";
import Link, { useNavigationVersionRef } from "./navigation-intent";
import styles from "./owner-layouts.module.css";

const widgetKinds = [
  "portfolio_summary",
  "direct_allocation",
  "holdings_preview",
  "data_quality",
  "saved_view",
] as const;
export function OwnerLayoutForm({
  initial,
  accounts,
  layoutId,
  revision,
}: Readonly<{
  initial: OwnerLayoutContent;
  accounts: readonly Account[];
  layoutId?: string;
  revision?: number;
}>) {
  const [content, setContent] = useState(initial);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const key = useRef<{ serialized: string; value: string } | null>(null);
  const navigation = useNavigationVersionRef();
  const router = useRouter();
  const current = `${usePathname()}?${useSearchParams()}`;
  const currentRef = useRef(current);
  useEffect(() => {
    currentRef.current = current;
  }, [current]);
  function patchWidget(index: number, widget: OwnerLayoutWidget) {
    setContent((old) => ({
      ...old,
      widgets: old.widgets.map((item, offset) =>
        offset === index ? widget : item,
      ),
    }));
  }
  function move(index: number, offset: number) {
    setContent((old) => {
      const widgets = [...old.widgets];
      [widgets[index], widgets[index + offset]] = [
        widgets[index + offset],
        widgets[index],
      ];
      return { ...old, widgets };
    });
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = OwnerLayoutContentSchema.safeParse(content);
    if (
      !parsed.success ||
      new TextEncoder().encode(JSON.stringify(content)).byteLength > 16384
    ) {
      setNotice(
        "Review the required selections and keep the complete layout within 16 KiB.",
      );
      return;
    }
    const serialized = JSON.stringify(parsed.data);
    if (key.current?.serialized !== serialized)
      key.current = { serialized, value: crypto.randomUUID() };
    const idempotency_key = key.current.value;
    const intent = navigation.current;
    startTransition(async () => {
      const result = await submitOwnerLayoutCommand(
        layoutId && revision
          ? {
              kind: "update",
              layout_id: layoutId,
              revision,
              body: { content: parsed.data },
              idempotency_key,
            }
          : { kind: "create", body: { content: parsed.data }, idempotency_key },
      );
      if (intent !== navigation.current || current !== currentRef.current)
        return;
      if (!result.ok) {
        setNotice(result.message);
        return;
      }
      if (result.kind !== "saved") {
        setNotice("The saved response was incompatible. Reload the layout.");
        return;
      }
      navigation.current += 1;
      router.push(
        ownerLayoutHref({
          layout: result.value.id,
          mode: "view",
          ...(result.value.content.account_id
            ? { account: result.value.content.account_id }
            : {}),
        }),
      );
      router.refresh();
    });
  }
  return (
    <form
      onSubmit={submit}
      className={styles.stack}
      aria-label={layoutId ? "Edit saved layout" : "Create saved layout"}
    >
      <fieldset
        disabled={pending}
        className={styles.stack}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >
        <legend>
          {layoutId
            ? `Create version ${(revision ?? 0) + 1}`
            : "New owner layout"}
        </legend>
        <div className={styles.fields}>
          <label>
            <span>Layout name</span>
            <input
              value={content.name}
              maxLength={80}
              required
              onChange={(event) =>
                setContent({ ...content, name: event.target.value })
              }
            />
          </label>
          <label>
            <span>Description</span>
            <input
              value={content.description}
              maxLength={400}
              onChange={(event) =>
                setContent({ ...content, description: event.target.value })
              }
            />
          </label>
          <label>
            <span>Bound account</span>
            <select
              value={content.account_id ?? ""}
              onChange={(event) =>
                setContent({
                  ...content,
                  account_id: event.target.value || null,
                })
              }
            >
              <option value="">Owner template — choose no account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Desktop columns</span>
            <select
              value={content.columns}
              onChange={(event) =>
                setContent({ ...content, columns: Number(event.target.value) })
              }
            >
              {[1, 2, 3].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Spacing</span>
            <select
              value={content.density}
              onChange={(event) =>
                setContent({
                  ...content,
                  density: event.target.value as typeof content.density,
                })
              }
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </label>
        </div>
        <p>
          Saved run and historical selections require one explicit account.
          Financial previews read the current canonical portfolio when opened.
        </p>
        <ol className={styles.widgets}>
          {content.widgets.map((widget, index) => (
            <li key={widget.id} className={styles.widget}>
              <h3>Widget {index + 1}</h3>
              <div className={styles.fields}>
                <label>
                  <span>Widget type</span>
                  <select
                    value={widget.kind}
                    onChange={(event) => {
                      const kind = event.target
                        .value as OwnerLayoutWidget["kind"];
                      patchWidget(index, {
                        ...widget,
                        kind,
                        selection:
                          kind === "saved_view"
                            ? initialLayoutSelection("workspace")
                            : null,
                      });
                    }}
                  >
                    {widgetKinds.map((kind) => (
                      <option
                        key={kind}
                        value={kind}
                        disabled={
                          kind !== "saved_view" &&
                          content.widgets.some(
                            (other) =>
                              other.id !== widget.id && other.kind === kind,
                          )
                        }
                      >
                        {kind.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Widget label (optional)</span>
                  <input
                    value={widget.label}
                    maxLength={80}
                    onChange={(event) =>
                      patchWidget(index, {
                        ...widget,
                        label: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              {widget.selection ? (
                <OwnerLayoutSelectionFields
                  value={widget.selection}
                  change={(selection) =>
                    patchWidget(index, { ...widget, selection })
                  }
                />
              ) : null}
              <div className={styles.toolbar}>
                <Button
                  type="button"
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                  aria-label={`Move widget ${index + 1} up`}
                >
                  Move up
                </Button>
                <Button
                  type="button"
                  disabled={index === content.widgets.length - 1}
                  onClick={() => move(index, 1)}
                  aria-label={`Move widget ${index + 1} down`}
                >
                  Move down
                </Button>
                <Button
                  type="button"
                  disabled={content.widgets.length === 1}
                  onClick={() =>
                    setContent({
                      ...content,
                      widgets: content.widgets.filter(
                        (item) => item.id !== widget.id,
                      ),
                    })
                  }
                  aria-label={`Remove widget ${index + 1}`}
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ol>
        <div className={styles.toolbar}>
          <Button
            type="button"
            disabled={content.widgets.length >= 24}
            onClick={() =>
              setContent({
                ...content,
                widgets: [
                  ...content.widgets,
                  {
                    id: crypto.randomUUID(),
                    kind: "saved_view",
                    label: "",
                    selection: initialLayoutSelection("workspace"),
                  },
                ],
              })
            }
          >
            Add widget
          </Button>
          <span>{content.widgets.length} of 24 widgets</span>
          <Button type="submit">
            {pending
              ? "Saving…"
              : layoutId
                ? "Save as new version"
                : "Create layout"}
          </Button>
        </div>
      </fieldset>
      {notice ? (
        <Notice title="Layout not saved">
          <p role="alert">{notice}</p>
          {layoutId ? (
            <Link
              prefetch={false}
              href={ownerLayoutHref({
                layout: layoutId,
                mode: "edit",
                ...(content.account_id ? { account: content.account_id } : {}),
              })}
            >
              Reload current revision
            </Link>
          ) : null}
        </Notice>
      ) : null}
    </form>
  );
}

export function ArchiveOwnerLayoutButton({
  layoutId,
  revision,
}: Readonly<{ layoutId: string; revision: number }>) {
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const key = useRef<string | null>(null);
  const navigation = useNavigationVersionRef();
  const router = useRouter();
  return (
    <div className={styles.stack}>
      <Button
        type="button"
        disabled={pending}
        onClick={() => {
          key.current ??= crypto.randomUUID();
          const idempotency_key = key.current;
          const intent = navigation.current;
          startTransition(async () => {
            const result = await submitOwnerLayoutCommand({
              kind: "archive",
              layout_id: layoutId,
              revision,
              idempotency_key,
            });
            if (intent !== navigation.current) return;
            if (!result.ok) {
              setNotice(result.message);
              return;
            }
            navigation.current += 1;
            router.push("/settings/layouts?archived=true");
            router.refresh();
          });
        }}
      >
        {pending ? "Archiving…" : "Archive layout"}
      </Button>
      {notice ? <p role="alert">{notice}</p> : null}
    </div>
  );
}
