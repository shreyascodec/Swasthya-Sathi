import { motion } from "framer-motion";

export type StepStatus = "done" | "active" | "pending";

export interface Step {
  label: string;
  status: StepStatus;
}

export function ProgressSteps({ steps }: { steps: Step[] }) {
  return (
    <div className="flex flex-col gap-0.5">
      {steps.map((step, i) => (
        <div key={step.label} className="flex items-start gap-3">
          <div className="flex flex-col items-center">
            <StepIcon status={step.status} />
            {i < steps.length - 1 && (
              <div
                className={`my-0.5 h-6 w-[2px] rounded-full ${
                  step.status === "done" ? "bg-primary-green" : "bg-secondary-green/30"
                }`}
              />
            )}
          </div>
          <p
            className={`pt-0.5 text-sm font-medium leading-tight ${
              step.status === "pending"
                ? "text-text-secondary/60"
                : step.status === "active"
                  ? "text-primary-dark"
                  : "text-text-primary"
            }`}
          >
            {step.label}
          </p>
        </div>
      ))}
    </div>
  );
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 350, damping: 18 }}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-green"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </motion.div>
    );
  }
  if (status === "active") {
    return (
      <div className="relative flex h-6 w-6 shrink-0 items-center justify-center">
        <motion.span
          className="absolute h-6 w-6 rounded-full bg-primary-green/30"
          animate={{ scale: [1, 1.5], opacity: [0.6, 0] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
        />
        <span className="h-3 w-3 rounded-full bg-primary-green" />
      </div>
    );
  }
  return <span className="h-6 w-6 shrink-0 rounded-full border-2 border-secondary-green/40 bg-white" />;
}
