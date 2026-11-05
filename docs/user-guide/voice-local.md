# Voz local

O perfil `personal-safe.toml` usa `faster-whisper` para a entrada de voz.
O áudio do microfone é enviado apenas ao servidor OpenJarvis em `127.0.0.1`
e a transcrição ocorre localmente. O perfil fixa o backend local, portanto
não recorre a OpenAI ou Deepgram caso essas chaves estejam presentes.

## Preparação

No ambiente virtual do projeto, instale a dependência de fala:

```bash
pip install -e '.[desktop]'
```

Na primeira inicialização, o Faster-Whisper pode baixar o modelo `base`.
Esse download obtém somente os pesos do modelo; nenhuma gravação ou
transcrição pessoal é enviada ao provedor do modelo.

## Interface local

```bash
cd /home/engle/workspace/OpenJarvis
source .venv/bin/activate
export OPENJARVIS_CONFIG="$PWD/configs/openjarvis/examples/personal-safe.toml"
jarvis serve
```

Em outra aba/terminal, inicie a interface já configurada para usar o servidor:

```bash
jarvis gui --no-server --frontend-port 5175
```

Abra `http://127.0.0.1:5175`, acesse **Settings** e habilite
**Speech-to-Text**. No chat, o botão de microfone inicia a gravação e o segundo
clique a encerra. A transcrição é inserida no campo de mensagem para revisão:
ela não envia um comando automaticamente.

## Terminal

Para a conversa por voz no terminal, use:

```bash
jarvis chat --voice
```

A entrada de voz funciona com o extra `desktop`. A leitura das respostas é
opcional e requer também um backend TTS local, como o extra `voice` e
`espeak-ng` no Linux. Deixe TTS desativado até instalar e testar esse backend.
