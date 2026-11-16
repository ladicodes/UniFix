import { SendHorizontal } from "lucide-react";

export default function MessagesIndex() {
  return (
    <div className="grid h-full place-items-center bg-plaster/50 p-10 text-center">
      <div>
        <span className="mx-auto grid size-16 place-items-center rounded-2xl bg-paper shadow-lift">
          <SendHorizontal className="size-7 text-ink" aria-hidden />
        </span>
        <p className="mt-5 text-lg font-semibold">Your messages</p>
        <p className="mx-auto mt-1 max-w-xs text-ink-3">
          Message any professional from their profile. Quotations, payment updates and photos all arrive here.
        </p>
      </div>
    </div>
  );
}
