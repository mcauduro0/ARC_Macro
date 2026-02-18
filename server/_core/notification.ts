import { TRPCError } from "@trpc/server";
import { ENV } from "./env";

export type NotificationPayload = {
  title: string;
  content: string;
};

const TITLE_MAX_LENGTH = 1200;
const CONTENT_MAX_LENGTH = 20000;

const trimValue = (value: string): string => value.trim();
const isNonEmptyString = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

const buildEndpointUrl = (baseUrl: string): string => {
  const normalizedBase = baseUrl.endsWith("/")
    ? baseUrl
    : `${baseUrl}/`;
  return new URL(
    "webdevtoken.v1.WebDevService/SendNotification",
    normalizedBase
  ).toString();
};

const validatePayload = (input: NotificationPayload): NotificationPayload => {
  if (!isNonEmptyString(input.title)) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "Notification title is required.",
    });
  }
  if (!isNonEmptyString(input.content)) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "Notification content is required.",
    });
  }

  const title = trimValue(input.title);
  const content = trimValue(input.content);

  if (title.length > TITLE_MAX_LENGTH) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: `Notification title must be at most ${TITLE_MAX_LENGTH} characters.`,
    });
  }

  if (content.length > CONTENT_MAX_LENGTH) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: `Notification content must be at most ${CONTENT_MAX_LENGTH} characters.`,
    });
  }

  return { title, content };
};

/**
 * Send notification via Manus Forge API (original implementation).
 */
async function notifyViaManus(title: string, content: string): Promise<boolean> {
  if (!ENV.forgeApiUrl || !ENV.forgeApiKey) {
    return false;
  }

  const endpoint = buildEndpointUrl(ENV.forgeApiUrl);

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${ENV.forgeApiKey}`,
        "content-type": "application/json",
        "connect-protocol-version": "1",
      },
      body: JSON.stringify({ title, content }),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      console.warn(
        `[Notification] Manus Forge failed (${response.status} ${response.statusText})${
          detail ? `: ${detail}` : ""
        }`
      );
      return false;
    }

    return true;
  } catch (error) {
    console.warn("[Notification] Manus Forge error:", error);
    return false;
  }
}

/**
 * Send notification via email (SMTP / nodemailer).
 * Used when Manus Forge is not available (DigitalOcean deployment).
 */
async function notifyViaEmail(title: string, content: string): Promise<boolean> {
  const smtpHost = process.env.SMTP_HOST;
  const smtpUser = process.env.SMTP_USER;
  const smtpPass = process.env.SMTP_PASS;
  const notifyEmail = process.env.NOTIFY_EMAIL || smtpUser;

  if (!smtpHost || !smtpUser || !smtpPass || !notifyEmail) {
    console.log(`[Notification] (no SMTP configured) ${title}\n${content}`);
    return true;
  }

  try {
    const nodemailer = await import("nodemailer");
    const port = parseInt(process.env.SMTP_PORT || "587");
    const transporter = nodemailer.default.createTransport({
      host: smtpHost,
      port,
      secure: port === 465,
      auth: { user: smtpUser, pass: smtpPass },
    });

    await transporter.sendMail({
      from: `"BRLUSD Dashboard" <${smtpUser}>`,
      to: notifyEmail,
      subject: `[BRLUSD] ${title}`,
      text: content,
      html: `<h3>${title}</h3><pre style="white-space:pre-wrap;font-family:monospace;">${content}</pre>`,
    });

    console.log(`[Notification] Email sent: ${title}`);
    return true;
  } catch (error) {
    console.warn("[Notification] Email send failed:", error);
    return true; // Don't block pipeline on notification failure
  }
}

/**
 * Dispatches a project-owner notification.
 * 
 * Strategy:
 * 1. If Manus Forge API is configured → use it (Manus hosting)
 * 2. If SMTP is configured → send email (DigitalOcean deployment)
 * 3. Otherwise → log to console (development)
 */
export async function notifyOwner(
  payload: NotificationPayload
): Promise<boolean> {
  const { title, content } = validatePayload(payload);

  // Try Manus Forge first (works on Manus hosting)
  if (ENV.forgeApiUrl && ENV.forgeApiKey) {
    const success = await notifyViaManus(title, content);
    if (success) return true;
    // Fall through to email if Forge fails
  }

  // Try email (works on DigitalOcean)
  return notifyViaEmail(title, content);
}
