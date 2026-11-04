/* A folha de gravação do atalho de clonagem: o texto que a pessoa lê em voz alta durante os 15 segundos. Como o texto é conhecido,
   ele vai junto como a transcrição da referência e o Whisper não precisa ouvir de novo. São frases corridas, com vogais e
   consoantes variadas e sem números nem siglas, que a pessoa lê sem tropeçar. */

/** A duração da gravação de referência: o servidor aproveita no máximo 15 s dela. */
export const CLONE_SECONDS = 15

const SCRIPTS: Record<string, string> = {
  pt: 'Olá, estou gravando a minha voz para o DMaker. Vou falar com calma e naturalidade, como quem conta a um amigo como foi a manhã: o café ficou pronto, o sol entrou pela janela e a cidade começou a acordar.',
  en: 'Hello, I am recording my voice for DMaker. I will speak calmly and naturally, the way you tell a friend about your morning: the coffee was ready, the sun came through the window, and the city began to wake up.',
  es: 'Hola, estoy grabando mi voz para DMaker. Voy a hablar con calma y naturalidad, como quien le cuenta a un amigo cómo fue la mañana: el café estaba listo, el sol entró por la ventana y la ciudad empezó a despertar.',
  fr: "Bonjour, j'enregistre ma voix pour DMaker. Je vais parler calmement et naturellement, comme on raconte sa matinée à un ami : le café était prêt, le soleil entrait par la fenêtre et la ville commençait à se réveiller.",
  de: 'Hallo, ich nehme meine Stimme für DMaker auf. Ich spreche ruhig und natürlich, so wie man einem Freund vom Morgen erzählt: Der Kaffee war fertig, die Sonne schien durch das Fenster und die Stadt begann aufzuwachen.',
  it: 'Ciao, sto registrando la mia voce per DMaker. Parlerò con calma e naturalezza, come si racconta a un amico la mattina: il caffè era pronto, il sole entrava dalla finestra e la città cominciava a svegliarsi.',
}

/** O texto da folha no idioma (o português se o idioma não tem folha). */
export function recordingScript(language: string): string {
  return SCRIPTS[language] ?? (SCRIPTS.pt as string)
}
