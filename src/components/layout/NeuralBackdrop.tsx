"use client";

const nodes = [
  { left: "7%", top: "12%", size: 5, delay: "0s" },
  { left: "18%", top: "32%", size: 3, delay: "0.8s" },
  { left: "31%", top: "18%", size: 4, delay: "1.4s" },
  { left: "46%", top: "46%", size: 7, delay: "0.4s" },
  { left: "59%", top: "21%", size: 3, delay: "2.1s" },
  { left: "72%", top: "38%", size: 5, delay: "1.1s" },
  { left: "84%", top: "15%", size: 4, delay: "2.7s" },
  { left: "91%", top: "64%", size: 6, delay: "0.2s" },
  { left: "63%", top: "78%", size: 3, delay: "1.8s" },
  { left: "28%", top: "72%", size: 5, delay: "2.4s" },
];

export function NeuralBackdrop() {
  return (
    <div aria-hidden className="hive-neural-backdrop">
      <div className="hive-neural-glow hive-neural-glow-cyan" />
      <div className="hive-neural-glow hive-neural-glow-violet" />
      <svg className="hive-neural-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
        <path d="M7 12 C18 32, 31 18, 46 46 S72 38, 84 15" />
        <path d="M18 32 C28 72, 46 46, 63 78 S84 15, 91 64" />
        <path d="M31 18 C59 21, 72 38, 91 64" />
      </svg>
      {nodes.map((node, index) => (
        <span
          key={`${node.left}-${node.top}`}
          className="hive-neural-node"
          style={{
            left: node.left,
            top: node.top,
            width: node.size,
            height: node.size,
            animationDelay: node.delay,
            opacity: index % 3 === 0 ? 0.9 : 0.55,
          }}
        />
      ))}
    </div>
  );
}
