/**
 * DigitalOcean Deployment — Email Notification Module
 * Replaces Manus Forge notifyOwner with nodemailer SMTP.
 * 
 * Required env vars:
 *   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_EMAIL
 * 
 * Falls back to console.log if SMTP is not configured.
 */
import nodemailer from "nodemailer";

export type NotificationPayload = {
  title: string;
  content: string;
};

let transporter: nodemailer.Transporter | null = null;

function getTransporter(): nodemailer.Transporter | null {
  if (transporter) return transporter;

  const host = process.env.SMTP_HOST;
  const port = parseInt(process.env.SMTP_PORT || "587");
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;

  if (!host || !user || !pass) {
    return null;
  }

  transporter = nodemailer.createTransport({
    host,
    port,
    secure: port === 465,
    auth: { user, pass },
  });

  return transporter;
}

export async function notifyOwner(
  payload: NotificationPayload
): Promise<boolean> {
  const { title, content } = payload;
  const notifyEmail = process.env.NOTIFY_EMAIL || process.env.SMTP_USER;

  const transport = getTransporter();

  if (!transport || !notifyEmail) {
    // Fallback: log to console if SMTP not configured
    console.log(`[Notification] ${title}\n${content}`);
    return true;
  }

  try {
    await transport.sendMail({
      from: `"BRLUSD Dashboard" <${process.env.SMTP_USER}>`,
      to: notifyEmail,
      subject: title,
      text: content,
      html: `<h3>${title}</h3><pre>${content}</pre>`,
    });
    return true;
  } catch (error) {
    console.warn("[Notification] Email send failed:", error);
    // Still return true to not block pipeline
    return true;
  }
}
